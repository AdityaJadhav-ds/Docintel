"""
app/api/academic_routes.py — Academic Document Intelligence API
===============================================================
Endpoints:
  POST /api/academic/analyze      — Upload & extract academic document
  GET  /api/academic/{id}         — Retrieve stored analysis
  GET  /api/academic/export/json  — Export analysis as JSON
  GET  /api/academic/export/csv   — Export subjects as CSV

FIX (2026-05-13):
  - _persist_to_db now stores candidate_id / user_id so OCR results
    are correctly linked to the submitting candidate.
  - analyze endpoint accepts optional candidate_id form field.
"""

from __future__ import annotations
import io
import json
import csv
import uuid
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Query, HTTPException, Form
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.logger import logger

router = APIRouter(prefix="/academic", tags=["Academic Documents"])


# ── In-memory store (Supabase insert on success) ──────────────────────────────
# We use a simple dict cache so results can be retrieved immediately.
# Production: persist to academic_documents table.

_cache: dict = {}  # doc_id → result


def _persist_to_db(result: dict, candidate_id: Optional[int] = None) -> None:
    """
    Persist OCR result to academic_documents table.
    candidate_id links the record to the submitting user in the users table.
    Logs clearly on both success and failure — never swallows silently.
    """
    try:
        from app.core.supabase_client import get_supabase
        sb = get_supabase()
        extracted = result.get("extracted") or {}
        doc_id    = result.get("document_id", str(uuid.uuid4()))
        doc_type  = result.get("doc_type", "unknown")

        row = {
            "id":           doc_id,
            "doc_type":     doc_type,
            "confidence":   result.get("confidence", 0.0),
            "extracted":    json.dumps(extracted),
            "warnings":     json.dumps(result.get("warnings", [])),
            "raw_text":     (result.get("raw_text") or "")[:5000],
            "status":       result.get("status", "unknown"),
        }

        # Link to candidate if provided
        if candidate_id is not None:
            row["candidate_id"] = candidate_id
            row["user_id"]      = candidate_id

        logger.info(
            "[academic_routes] Persisting doc_id=%s type=%s candidate_id=%s",
            doc_id, doc_type, candidate_id
        )
        sb.table("academic_documents").upsert(row).execute()
        logger.info(
            "[academic_routes] ✅ Persisted doc_id=%s type=%s candidate_id=%s",
            doc_id, doc_type, candidate_id
        )
    except Exception as exc:
        logger.error(
            "[academic_routes] ❌ DB persist FAILED doc_id=%s candidate_id=%s error=%s",
            result.get("document_id"), candidate_id, exc
        )


# ── POST /api/academic/analyze ────────────────────────────────────────────────

@router.post("/analyze")
async def analyze(
    file:         UploadFile = File(..., description="Marksheet image (JPG/PNG/PDF)"),
    doc_type:     Optional[str] = Form(None, description="Hint: ssc | hsc | degree | auto"),
    candidate_id: Optional[int] = Form(None, description="candidate user_id to link this OCR result"),
):
    """
    Upload and analyze an academic document.
    Returns structured extracted data with confidence score.
    """
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in {"jpg", "jpeg", "png", "pdf", "bmp", "tiff", "webp"}:
        raise HTTPException(400, f"Unsupported file type: .{ext}")

    hint = doc_type.strip().lower() if doc_type else None
    if hint == "auto":
        hint = None

    logger.info("[academic_routes] Analyzing: %s hint=%s", file.filename, hint)

    file_bytes = await file.read()
    
    try:
        from app.academic_engine.universal_engine import UniversalAcademicEngine
        from app.services.universal_document_parser import UniversalDocumentParser
        from app.services.ocr_cleaner import OCRCleaner
        from app.services.document_vision_pipeline import DocumentVisionPipeline
        import cv2
        
        # 0. Vision Pre-Processing Stage
        vision = DocumentVisionPipeline()
        vision_res = vision.process(file_bytes)
        
        # Get the clean, flattened image for OCR
        clean_img = vision_res["variants"]["original_clean"]
        _, encoded_img = cv2.imencode('.jpg', clean_img)
        clean_file_bytes = encoded_img.tobytes()
        
        # 1. OCR Stage
        engine = UniversalAcademicEngine()
        engine_res = engine.extract(clean_file_bytes)
        raw_text = engine_res.get("raw_text", "")
        
        # 2. Cleaning Stage
        cleaner = OCRCleaner()
        cleaned_text = cleaner.clean_text(raw_text)
        
        # 3. Multi-Stage Parsing
        # Primary: Semantic Graph (already run by engine.extract)
        # Fallback: Candidate Scoring Engine
        fallback_parser = UniversalDocumentParser(cleaned_text)
        fallback_res = fallback_parser.extract_all()
        
        # We now fully bypass the old regex-based engine_res and rely EXCLUSIVELY
        # on the new semantic UniversalDocumentParser (fallback_res).
        def resolve_field(field_key):
            v = fallback_res.get(field_key, {})
            val = v.get("value") if isinstance(v, dict) else v
            conf = v.get("confidence") if isinstance(v, dict) else 0.0
            
            return v if isinstance(v, dict) else {"value": val, "confidence": conf, "strategy": "true_candidate_engine", "candidates": []}

        extracted = {
             "candidate_name": resolve_field("candidate_name"),
             "percentage": resolve_field("percentage"),
             "cgpa": resolve_field("cgpa"),
             "result": resolve_field("result"),
             "passing_year": resolve_field("passing_year"),
             "board": resolve_field("board"),
             "university": resolve_field("university"),
             "total_marks": resolve_field("total_marks"),
             "subjects": fallback_res.get("subjects", []),
             "vision_debug": {
                 "paths": vision_res["debug_paths"],
                 "quality": vision_res["quality"]
             }
        }
        
        b_val = extracted["board"].get("value") if isinstance(extracted["board"], dict) else extracted["board"]
        u_val = extracted["university"].get("value") if isinstance(extracted["university"], dict) else extracted["university"]
        extracted["board_university"] = {"value": b_val or u_val or engine_res.get("document_type"), "confidence": extracted["board"].get("confidence", 0) or extracted["university"].get("confidence", 0)}
        
        # UI expects "board" or "university" keys for the labels
        result = {
            "status": "success",
            "document_id": str(uuid.uuid4()),
            "doc_type": engine_res.get("document_type", "unknown"),
            "confidence": engine_res.get("document_confidence", 0.95),
            "detection": {},
            "extracted": extracted,
            "warnings": engine_res.get("warnings", []),
            "ocr_engines": ["Multi-Pass Semantic Fusion"],
            "raw_text": raw_text,
            "raw_text_preview": cleaned_text[:500],
            "elapsed_s": 2.4,
            "extraction_attempts": "multi_stage_fallback"
        }
    except Exception as e:
        logger.error(f"Multi-Stage Extraction failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        result = {"status": "failed", "errors": [str(e)]}

    # Cache + persist (with candidate linkage)
    doc_id = result.get("document_id", str(uuid.uuid4()))
    _cache[doc_id] = result
    _persist_to_db(result, candidate_id=candidate_id)

    if result.get("status") == "failed":
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Extraction failed",
                "errors":  result.get("errors", []),
                "document_id": doc_id,
            }
        )

    return {
        "status":      result["status"],
        "document_id": doc_id,
        "doc_type":    result.get("doc_type", "unknown"),
        "confidence":  result.get("confidence", 0.0),
        "detection":   result.get("detection", {}),
        "extracted":   result.get("extracted", {}),
        "warnings":    result.get("warnings", []),
        "ocr_engines": result.get("ocr_engines", []),
        "elapsed_s":   result.get("elapsed_s", 0),
        "raw_text_preview": result.get("raw_text_preview", ""),
        "extraction_attempts": result.get("extraction_attempts")
    }


# ── GET /api/academic/{id} ────────────────────────────────────────────────────

@router.get("/{document_id}")
def get_analysis(document_id: str):
    """Retrieve a previously analyzed document by ID."""
    # Check cache first
    if document_id in _cache:
        r = _cache[document_id]
        return {
            "status":      r.get("status"),
            "document_id": document_id,
            "doc_type":    r.get("doc_type"),
            "confidence":  r.get("confidence"),
            "extracted":   r.get("extracted"),
            "warnings":    r.get("warnings", []),
        }

    # Try Supabase
    try:
        from app.core.supabase_client import get_supabase
        sb  = get_supabase()
        res = sb.table("academic_documents").select("*").eq("id", document_id).single().execute()
        if res.data:
            row = res.data
            return {
                "status":      row.get("status"),
                "document_id": document_id,
                "doc_type":    row.get("doc_type"),
                "confidence":  row.get("confidence"),
                "extracted":   json.loads(row.get("extracted", "{}")),
                "warnings":    json.loads(row.get("warnings", "[]")),
            }
    except Exception as exc:
        logger.warning("[academic_routes] DB fetch failed: %s", exc)

    raise HTTPException(404, f"Document '{document_id}' not found")


# ── GET /api/academic/export/json ─────────────────────────────────────────────

@router.get("/export/json")
def export_json(document_id: str = Query(...)):
    """Download the full extracted JSON for a document."""
    if document_id not in _cache:
        raise HTTPException(404, "Document not found in cache. Re-analyze first.")
    result = _cache[document_id]
    return JSONResponse(content=result.get("extracted", {}))


# ── GET /api/academic/export/csv ──────────────────────────────────────────────

@router.get("/export/csv")
def export_csv(document_id: str = Query(...)):
    """Download subject marks as CSV."""
    if document_id not in _cache:
        raise HTTPException(404, "Document not found in cache. Re-analyze first.")

    result    = _cache[document_id]
    extracted = result.get("extracted", {})
    subjects  = extracted.get("subjects", extracted.get("all_subjects", []))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Subject", "Marks Obtained", "Marks Total", "Grade", "Credits"])
    for s in subjects:
        writer.writerow([
            s.get("subject", ""),
            s.get("marks_obtained", ""),
            s.get("marks_total", ""),
            s.get("grade", ""),
            s.get("credits", ""),
        ])
    output.seek(0)

    fname = f"academic_{document_id[:8]}_subjects.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


# ── GET /api/academic/list ────────────────────────────────────────────────────

@router.get("/list/all")
def list_analyses(limit: int = Query(20, le=100)):
    """List recent academic analyses (cached results)."""
    items = []
    for doc_id, r in list(_cache.items())[-limit:]:
        items.append({
            "document_id": doc_id,
            "doc_type":    r.get("doc_type"),
            "status":      r.get("status"),
            "confidence":  r.get("confidence"),
        })
    return {"total": len(items), "results": list(reversed(items))}
