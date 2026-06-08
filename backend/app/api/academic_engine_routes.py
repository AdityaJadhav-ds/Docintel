"""
app/api/academic_engine_routes.py — Academic Engine v2 API
===========================================================
Endpoints:
  POST /api/v2/academic/analyze        Upload & extract academic document
  POST /api/v2/academic/analyze/bulk   Bulk upload (multi-file)
  GET  /api/v2/academic/{doc_id}       Retrieve stored result
  GET  /api/v2/academic/export/json    Download JSON
  GET  /api/v2/academic/list           List recent analyses
  GET  /api/v2/academic/debug/{doc_id} Debug artefact metadata

COMPLETELY ISOLATED from KYC / Aadhaar / PAN routes.
Uses the new academic_engine/ pipeline (not app/academic/).
"""

from __future__ import annotations
import json
import uuid
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import JSONResponse

from app.core.logger import logger
from app.academic_engine.master_pipeline import MasterPipeline

router = APIRouter(prefix="/v2/academic", tags=["Academic Engine v2"])

# ── In-memory result cache (also persisted to Supabase) ───────────────────────
_cache: dict = {}


def _cache_store(doc_id: str, result: dict) -> None:
    _cache[doc_id] = result


def _cache_get(doc_id: str) -> Optional[dict]:
    return _cache.get(doc_id)


def _persist(doc_id: str, result: dict) -> None:
    """Best-effort Supabase upsert — never raises."""
    try:
        from app.core.supabase_client import get_supabase
        sb      = get_supabase()
        meta    = result.get("_meta", {})
        conf    = meta.get("confidence", {})
        row = {
            "id":               doc_id,
            "document_category": result.get("document_category"),
            "document_type":    result.get("document_type"),
            "candidate_name":   result.get("candidate_name"),
            "board_university": result.get("board_university"),
            "passing_year":     result.get("passing_year"),
            "percentage":       result.get("percentage"),
            "cgpa":             result.get("cgpa"),
            "grade_class":      result.get("grade_class"),
            "result":           result.get("result"),
            "confidence":       conf.get("overall", 0.0),
            "status":           meta.get("status"),
            "elapsed_s":        meta.get("elapsed_s"),
        }
        sb.table("academic_engine_results").upsert(row).execute()
        logger.info("[academic_engine_routes] Persisted doc_id=%s", doc_id)
    except Exception as exc:
        logger.warning("[academic_engine_routes] DB persist failed (non-fatal): %s", exc)


def _format_response(result: dict) -> dict:
    """Robust response including raw text and debug details for failsafe rendering."""
    meta = result.get("_meta", {})
    conf = meta.get("confidence", {})
    
    # Phase 6 Failsafe Response System
    return {
        "document_id":      meta.get("document_id"),
        "status":           meta.get("status", "unknown"),
        "document_category": result.get("document_category", "unknown"),
        "document_type":    result.get("document_type", "unknown"),
        # Only verified fields — None if not found
        "candidate_name":   result.get("candidate_name"),
        "board_university": result.get("board_university"),
        "passing_year":     result.get("passing_year"),
        "percentage":       result.get("percentage"),
        "cgpa":             result.get("cgpa"),
        "grade_class":      result.get("grade_class"),
        "result":           result.get("result"),
        # Confidence summary
        "confidence": {
            "overall":      conf.get("overall", 0.0),
            "grade":        conf.get("grade", "low"),
            "field_scores": conf.get("field_scores", {}),
            "coverage":     conf.get("coverage", 0.0),
        },
        "elapsed_s":    meta.get("elapsed_s", 0.0),
        "ocr_engines":  meta.get("ocr_engines", []),
        "warnings":     meta.get("warnings", []),
        "raw_text":     result.get("raw_text", ""),
        "debug_reason": "Extraction successful" if meta.get("status") in ("success", "partial") else "Insufficient reliable fields extracted",
        "extraction_attempts": meta.get("extraction_engine", "unknown"),
        "preprocessing_preview": "Available in debug metadata",
        "layout_v2_meta": meta.get("layout_v2_meta", {}),
    }


# ── POST /api/v2/academic/analyze ─────────────────────────────────────────────

@router.post("/analyze", summary="Analyze a single academic document")
async def analyze_single(
    file:     UploadFile = File(..., description="Marksheet or Certificate (JPG/PNG/PDF/WEBP/TIFF)"),
    doc_type: Optional[str] = Form(None, description="Hint: ssc | hsc | degree | auto"),
):
    """
    Upload and analyze an academic document.

    Accepts:
    - Mobile photos, WhatsApp images, scanned images, screenshots
    - PDFs (digital or scanned)
    - Low-light, tilted, compressed, partially cropped documents

    Returns:
    - document_category, document_type, candidate_name, board_university,
      passing_year, percentage, cgpa, grade_class, result
    - Only fields ACTUALLY present in the document (null otherwise)
    """
    if not file or not file.filename:
        raise HTTPException(400, "No file provided")

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    allowed = {"jpg", "jpeg", "png", "pdf", "bmp", "tiff", "tif", "webp", "heic", "heif"}
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: .{ext}. Allowed: {', '.join(sorted(allowed))}")

    hint    = (doc_type or "").strip().lower() or None
    if hint == "auto":
        hint = None

    doc_id     = str(uuid.uuid4())
    file_bytes = await file.read()

    logger.info("[academic_engine_routes] request received: file=%s size=%d hint=%s doc_id=%s",
                file.filename, len(file_bytes), hint, doc_id)
    logger.info("[academic_engine_routes] pipeline started for doc_id=%s", doc_id)

    try:
        import numpy as np
        import cv2
        import traceback

        if ext == "pdf":
            # ── PDF path: render pages → MasterPipeline (STEP 7 fix) ──
            from app.academic_engine.pdf_engine import PDFPipeline
            pdf_pipeline = PDFPipeline()
            result = pdf_pipeline.process(file_bytes, upload_id=doc_id)
        else:
            # ── Image path: existing logic untouched ──────────────────
            nparr = np.frombuffer(file_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if image is None:
                raise HTTPException(400, "Invalid image data — could not decode")

            pipeline = MasterPipeline()
            result = pipeline.process_document(image)

    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"[academic_engine_routes] Fatal route exception: {str(e)}\n{tb}")
        result = {
            "status": "error",
            "message": f"Fatal Route Error: {str(e)}",
            "extracted_data": {"fields": {}, "table_data": {}},
            "telemetry": {
                "debug_trace": {"final_status": "fatal_error"},
                "warnings": ["Fatal API route error"]
            },
            "debug_lab": {
                "traceback": tb
            }
        }
    
    # Adding doc_id for legacy compatibility
    if 'telemetry' not in result:
        result['telemetry'] = {}
    result['telemetry']['document_id'] = doc_id

    logger.info("[academic_engine_routes] extraction payload before response: %s", {k:v for k,v in result.items() if k not in ['_meta', 'raw_text']})

    _cache_store(doc_id, result)
    _persist(doc_id, result)

    formatted = result
    logger.info("[academic_engine_routes] pipeline finished for doc_id=%s, status=%s", doc_id, result.get("status", "unknown"))
    logger.info("[academic_engine_routes] final JSON response: %s", json.dumps(formatted, default=str)[:500])
    
    return formatted


# ── POST /api/v2/academic/analyze/bulk ────────────────────────────────────────

@router.post("/analyze/bulk", summary="Analyze multiple academic documents")
async def analyze_bulk(
    files:    List[UploadFile] = File(..., description="Multiple academic documents"),
    doc_type: Optional[str]    = Form(None, description="Hint applied to all files"),
):
    """
    Bulk upload endpoint — processes all files concurrently.
    Returns list of results in same order as uploaded files.
    """
    if not files:
        raise HTTPException(400, "No files provided")
    if len(files) > 20:
        raise HTTPException(400, "Maximum 20 files per bulk request")

    hint = (doc_type or "").strip().lower() or None
    if hint == "auto":
        hint = None

    file_bytes_list = []
    for f in files:
        data = await f.read()
        file_bytes_list.append(data)

    logger.info("[academic_engine_routes] bulk: %d files hint=%s", len(files), hint)

    results = []
    import numpy as np
    import cv2
    import traceback
    from app.academic_engine.pdf_engine import PDFPipeline
    image_pipeline = MasterPipeline()
    pdf_pipeline   = PDFPipeline()

    for idx, (file_bytes, f) in enumerate(zip(file_bytes_list, files)):
        bulk_ext = (f.filename or "").rsplit(".", 1)[-1].lower()
        bulk_id  = str(uuid.uuid4())[:8]
        try:
            if bulk_ext == "pdf":
                # PDF path: render → MasterPipeline
                results.append(pdf_pipeline.process(file_bytes, upload_id=bulk_id))
            else:
                # Image path: existing logic untouched
                nparr = np.frombuffer(file_bytes, np.uint8)
                img   = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if img is not None:
                    results.append(image_pipeline.process_document(img))
                else:
                    results.append({"status": "error", "message": "Invalid image data"})
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[academic_engine_routes] Fatal route bulk exception: {str(e)}\n{tb}")
            results.append({
                "status": "error",
                "message": f"Fatal Bulk Error: {str(e)}",
                "extracted_data": {"fields": {}, "table_data": {}},
                "telemetry": {
                    "debug_trace": {"final_status": "fatal_error"},
                    "warnings": ["Fatal API bulk route error"]
                },
                "debug_lab": {
                    "traceback": tb
                }
            })

    formatted = []
    for r in results:
        doc_id = r.get("telemetry", {}).get("document_id", str(uuid.uuid4()))
        _cache_store(doc_id, r)
        # Persistent storage not fully mapped to new schema yet
        # _persist(doc_id, r) 
        formatted.append(r)

    return {
        "total":   len(formatted),
        "results": formatted,
    }


# ── GET /api/v2/academic/{doc_id} ─────────────────────────────────────────────

@router.get("/{document_id}", summary="Get analysis result by document ID")
def get_analysis(document_id: str):
    """Retrieve a previously analysed document by its ID."""
    # Cache hit
    r = _cache_get(document_id)
    if r:
        return _format_response(r)

    # Try Supabase
    try:
        from app.core.supabase_client import get_supabase
        sb  = get_supabase()
        res = sb.table("academic_engine_results").select("*").eq("id", document_id).single().execute()
        if res.data:
            row = res.data
            return {
                "document_id":      document_id,
                "status":           row.get("status"),
                "document_category": row.get("document_category"),
                "document_type":    row.get("document_type"),
                "candidate_name":   row.get("candidate_name"),
                "board_university": row.get("board_university"),
                "passing_year":     row.get("passing_year"),
                "percentage":       row.get("percentage"),
                "cgpa":             row.get("cgpa"),
                "grade_class":      row.get("grade_class"),
                "result":           row.get("result"),
                "confidence": {
                    "overall": row.get("confidence"),
                },
                "elapsed_s": row.get("elapsed_s"),
            }
    except Exception as exc:
        logger.warning("[academic_engine_routes] DB fetch failed: %s", exc)

    raise HTTPException(404, f"Document '{document_id}' not found")


# ── GET /api/v2/academic/export/json ──────────────────────────────────────────

@router.get("/export/json", summary="Download analysis as JSON")
def export_json(document_id: str = Query(...)):
    """Download extracted fields as a clean JSON file."""
    r = _cache_get(document_id)
    if not r:
        raise HTTPException(404, "Document not in cache. Re-analyze first.")
    clean = _format_response(r)
    return JSONResponse(content=clean, headers={
        "Content-Disposition": f'attachment; filename="academic_{document_id[:8]}.json"'
    })


# ── GET /api/v2/academic/list ─────────────────────────────────────────────────

@router.get("/list/all", summary="List recent analyses")
def list_analyses(limit: int = Query(20, le=100)):
    """List most recent academic analyses from cache."""
    items = []
    cache_items = list(_cache.items())[-limit:]
    for doc_id, r in reversed(cache_items):
        meta = r.get("_meta", {})
        conf = meta.get("confidence", {})
        items.append({
            "document_id":      doc_id,
            "document_category": r.get("document_category"),
            "document_type":    r.get("document_type"),
            "status":           meta.get("status"),
            "confidence":       conf.get("overall"),
            "elapsed_s":        meta.get("elapsed_s"),
        })
    return {"total": len(items), "results": items}


# ── GET /api/v2/academic/debug/{doc_id} ───────────────────────────────────────

@router.get("/debug/{document_id}", summary="Debug artefact metadata")
def get_debug_info(document_id: str):
    """Return debug metadata for a document (if ACADEMIC_ENGINE_DEBUG=1)."""
    import os
    from pathlib import Path

    debug_dir = Path(os.environ.get("ACADEMIC_DEBUG_DIR", "academic_debug")) / document_id
    if not debug_dir.exists():
        raise HTTPException(404, f"No debug artefacts found for doc_id={document_id!r}. "
                                 f"Enable ACADEMIC_ENGINE_DEBUG=1 and re-analyze.")

    files = [
        {"name": f.name, "size_bytes": f.stat().st_size}
        for f in sorted(debug_dir.iterdir())
        if f.is_file()
    ]

    # Try to load extracted fields + confidence from JSON artefacts
    extracted_data = {}
    confidence_data = {}
    for json_file in debug_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            if "extracted_fields" in json_file.name:
                extracted_data = data
            elif "confidence" in json_file.name:
                confidence_data = data
        except Exception:
            pass

    return {
        "document_id": document_id,
        "debug_dir":   str(debug_dir),
        "artefacts":   files,
        "extracted":   extracted_data,
        "confidence":  confidence_data,
    }
