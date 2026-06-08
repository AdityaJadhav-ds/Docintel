"""
app/services/validation_service.py — High-level validation service
====================================================================
process_user_documents(user_id) is the top-level entry point.

Flow:
  1. Fetch user record from Supabase
  2. Fetch all documents for user
  3. Download each document from Supabase Storage
  4. Run OCR pipeline on each document
  5. Compare extracted fields vs stored user data
  6. Save validation results to Supabase
  7. Return structured JSON response

Performance optimisation (v3):
  - Fraud analysis dispatched to a daemon thread (fire-and-forget).
    The fraud pipeline makes 8+ Supabase round-trips (image hashing,
    tamper detection, duplicate full-table scans, 4 DB writes).
    Moving it off the critical path cuts per-document time by ~50-150s.
  - All stages timed with [TIMING] log lines for profiling.
"""

from __future__ import annotations
import io
import time
import threading
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.services.ocr_pipeline import process_document
from app.matchers.mismatch_detector import build_validation_result
from app.review.review_engine import submit_for_review
from app.fraud.fraud_engine import analyze_document as run_fraud_analysis


# ── Timing helper ─────────────────────────────────────────────────────────────

def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _fetch_user(user_id: int) -> Optional[Dict]:
    sb = get_supabase()
    res = sb.table("users").select("*").eq("id", user_id).single().execute()
    return res.data if res.data else None


def _fetch_documents(user_id: int) -> List[Dict]:
    sb = get_supabase()
    res = (
        sb.table("documents")
        .select("*")
        .eq("user_id", user_id)
        .order("uploaded_at", desc=True)
        .execute()
    )
    return res.data or []


def _download_document(storage_path: str) -> Optional[bytes]:
    """Download file bytes from Supabase Storage bucket 'documents'."""
    try:
        sb = get_supabase()
        response = sb.storage.from_("documents").download(storage_path)
        return response
    except Exception as exc:
        logger.error("[validation_service] Download failed for %s: %s", storage_path, exc)
        return None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _save_extracted_data(user_id: int, doc_type: str, version: int,
                          extracted: Dict, confidence: float) -> None:
    """
    Save extracted OCR data to Supabase.
    DELETE existing rows then INSERT fresh to guarantee freshest row wins.
    """
    sb = get_supabase()
    now = _utcnow_iso()
    payload = {
        "user_id":          user_id,
        "doc_type":         doc_type,
        "version":          version,
        "name":             extracted.get("name"),
        "aadhaar_number":   extracted.get("aadhaar_number"),
        "pan_number":       extracted.get("pan_number"),
        "dob":              extracted.get("dob"),
        "confidence_score": confidence,
        "processed_at":     now,
    }
    try:
        del_res = (
            sb.table("extracted_data")
            .delete()
            .eq("user_id", user_id)
            .eq("doc_type", doc_type)
            .execute()
        )
        deleted = len(del_res.data or [])
        if deleted:
            logger.info(
                "[validation_service] Deleted %d stale extracted_data row(s) for user=%s doc_type=%s",
                deleted, user_id, doc_type,
            )
        sb.table("extracted_data").insert(payload).execute()
        logger.info(
            "[validation_service] Saved fresh extracted_data for user=%s doc_type=%s conf=%.3f",
            user_id, doc_type, confidence,
        )
    except Exception as exc:
        logger.warning("[validation_service] Delete+Insert failed (%s), falling back to upsert", exc)
        try:
            sb.table("extracted_data").upsert(
                payload, on_conflict="user_id,doc_type,version"
            ).execute()
        except Exception as exc2:
            logger.error("[validation_service] Failed to save extracted_data: %s", exc2)


def _save_verification_result(user_id: int, doc_type: str, version: int,
                                validation_result: Dict) -> None:
    sb = get_supabase()
    overall = validation_result["overall_status"]
    fields  = validation_result.get("fields", [])

    def _field_matched(field_name: str) -> bool:
        for f in fields:
            if f["field"] == field_name:
                return f["status"] == "MATCH"
        return False

    payload = {
        "user_id":    user_id,
        "doc_type":   doc_type,
        "version":    version,
        "status":     overall,
        "name_match": _field_matched("name"),
        "id_match":   _field_matched("aadhaar_number") or _field_matched("pan_number"),
        "dob_match":  _field_matched("dob"),
    }
    try:
        sb.table("verified_data").upsert(
            payload, on_conflict="user_id,doc_type,version"
        ).execute()
        logger.info("[validation_service] Saved verified_data status=%s", overall)
    except Exception as exc:
        logger.error("[validation_service] Failed to save verified_data: %s", exc)


# ── Core per-document processor ───────────────────────────────────────────────

def _process_single_document(user: Dict, doc: Dict) -> Dict:
    user_id  = user["id"]
    doc_type = doc.get("doc_type", "unknown")
    version  = doc.get("version", 1)
    path     = doc.get("storage_path", "")
    doc_id   = doc.get("id")
    tag      = f"user={user_id} doc={doc_id} type={doc_type}"

    t_doc = time.perf_counter()
    logger.info("[validation_service] Processing doc_id=%s type=%s version=%s", doc_id, doc_type, version)

    # ── Stage 1: Download ─────────────────────────────────────────────────────
    t0 = time.perf_counter()
    raw_bytes = _download_document(path)
    logger.info("[TIMING] %s  stage=download  %dms  size=%dKB",
                tag, _ms(t0), len(raw_bytes or b"") // 1024)

    if not raw_bytes:
        return {
            "doc_id":          doc_id,
            "doc_type":        doc_type,
            "overall_status":  "OCR_FAILED",
            "fields":          [],
            "ocr_confidence":  0.0,
            "summary":         "Failed to download document from storage.",
            "error":           "Download failed.",
        }

    # ── Stage 2: OCR pipeline ─────────────────────────────────────────────────
    t0 = time.perf_counter()
    pipeline_result = process_document(io.BytesIO(raw_bytes), doc_type_hint=doc_type)
    logger.info("[TIMING] %s  stage=ocr_pipeline  %dms  conf=%.3f",
                tag, _ms(t0), pipeline_result.get("ocr_confidence", 0))

    # ── Stage 3: Validation / field matching ─────────────────────────────────
    t0 = time.perf_counter()
    validation_result = build_validation_result(
        doc_type       = pipeline_result["doc_type"],
        stored_user    = user,
        extracted      = pipeline_result["extracted"],
        ocr_confidence = pipeline_result["ocr_confidence"],
        variant_texts  = pipeline_result.get("variant_texts", {}),
    )
    logger.info("[TIMING] %s  stage=validation  %dms  status=%s",
                tag, _ms(t0), validation_result.get("overall_status"))

    # ── Stage 4: Save extracted data ─────────────────────────────────────────
    t0 = time.perf_counter()
    _save_extracted_data(user_id, doc_type, version,
                         pipeline_result["extracted"],
                         pipeline_result["ocr_confidence"])
    logger.info("[TIMING] %s  stage=save_extracted  %dms", tag, _ms(t0))

    # ── Stage 5: Save verification result ────────────────────────────────────
    t0 = time.perf_counter()
    _save_verification_result(user_id, doc_type, version, validation_result)
    logger.info("[TIMING] %s  stage=save_verified  %dms", tag, _ms(t0))

    # ── Stage 6: Review engine ────────────────────────────────────────────────
    t0 = time.perf_counter()
    review_id = None
    decision  = None
    try:
        review_result = submit_for_review(
            user_id           = user_id,
            doc_type          = pipeline_result["doc_type"],
            ocr_confidence    = pipeline_result["ocr_confidence"],
            validation_result = validation_result,
            extracted         = pipeline_result["extracted"],
            document_id       = doc_id,
        )
        review_id = review_result.get("review_id")
        decision  = review_result.get("decision")
        logger.info("[validation_service] Review created review_id=%s decision=%s", review_id, decision)
    except Exception as exc:
        logger.error("[validation_service] Review submission failed: %s", exc)
    logger.info("[TIMING] %s  stage=review_engine  %dms  decision=%s", tag, _ms(t0), decision)

    # ── Stage 7: Fraud analysis — fire-and-forget ─────────────────────────────
    # The fraud pipeline (image hashing, tamper detection, duplicate DB full-table
    # scans, 8+ Supabase writes) is ANALYTICAL work that does not affect OCR
    # accuracy or the primary save path. Running it synchronously was the primary
    # cause of 50-150s/record slowness. Dispatched to a daemon thread so the
    # critical path (download → OCR → save → review) completes immediately.
    _fraud_bytes     = raw_bytes
    _fraud_doc_id    = doc_id
    _fraud_user_id   = user_id
    _fraud_doc_type  = pipeline_result["doc_type"]
    _fraud_conf      = pipeline_result["ocr_confidence"]
    _fraud_extracted = pipeline_result.get("extracted", {})

    def _run_fraud_bg():
        try:
            t_f = time.perf_counter()
            run_fraud_analysis(
                image_input    = io.BytesIO(_fraud_bytes),
                user_id        = _fraud_user_id,
                doc_type       = _fraud_doc_type,
                document_id    = _fraud_doc_id,
                ocr_confidence = _fraud_conf,
                extracted      = _fraud_extracted,
            )
            logger.info("[TIMING] user=%s doc=%s  stage=fraud_bg  %dms",
                        _fraud_user_id, _fraud_doc_id,
                        int((time.perf_counter() - t_f) * 1000))
        except Exception as exc:
            logger.error("[validation_service] Background fraud analysis failed: %s", exc)

    threading.Thread(target=_run_fraud_bg, daemon=True).start()
    logger.info("[TIMING] %s  stage=fraud_dispatched", tag)

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("[TIMING] %s  stage=TOTAL_DOC  %dms", tag, _ms(t_doc))

    return {
        "doc_id":           doc_id,
        "doc_type":         doc_type,
        "version":          version,
        **validation_result,
        "extracted":        pipeline_result.get("extracted", {}),
        "ocr_confidence":   pipeline_result.get("ocr_confidence", 0.0),
        "raw_text_preview": pipeline_result["raw_text"][:500] if pipeline_result.get("raw_text") else "",
        "engines_used":     pipeline_result.get("engines_used", []),
        "review_id":        review_id,
        "decision":         decision,
        "fraud":            {},   # fraud result is async — not returned inline
    }


# ── Public entry point ────────────────────────────────────────────────────────

def process_user_documents(user_id: int) -> Dict:
    """
    Main entry point: validate all uploaded documents for a user.
    Returns structured JSON-serializable result.
    """
    t_user = time.perf_counter()
    logger.info("[validation_service] Starting for user_id=%s", user_id)

    # Stage: fetch user
    t0 = time.perf_counter()
    user = _fetch_user(user_id)
    logger.info("[TIMING] user=%s  stage=fetch_user  %dms", user_id, _ms(t0))

    if not user:
        return {
            "success":  False,
            "user_id":  user_id,
            "error":    f"User {user_id} not found in database.",
            "results":  [],
        }

    # Stage: fetch documents list
    t0 = time.perf_counter()
    documents = _fetch_documents(user_id)
    logger.info("[TIMING] user=%s  stage=fetch_docs  %dms  count=%d",
                user_id, _ms(t0), len(documents))

    if not documents:
        return {
            "success":   False,
            "user_id":   user_id,
            "user_name": user.get("full_name"),
            "error":     "No documents found for this user.",
            "results":   [],
        }

    # Process each document sequentially within a user. OCR parallelism is
    # managed at the user-batch level by the bulk worker, not within a single user.
    results = []
    for doc in documents:
        result = _process_single_document(user, doc)
        results.append(result)

    # Overall summary
    all_statuses = [r.get("overall_status") for r in results]
    if "MISMATCH" in all_statuses:
        overall = "MISMATCH"
    elif "POSSIBLE_MISMATCH" in all_statuses:
        overall = "POSSIBLE_MISMATCH"
    elif all(s == "VERIFIED" for s in all_statuses):
        overall = "VERIFIED"
    else:
        overall = "PARTIAL"

    logger.info("[TIMING] user=%s  stage=TOTAL_USER  %dms  docs=%d  status=%s",
                user_id, _ms(t_user), len(documents), overall)

    return {
        "success":        True,
        "user_id":        user_id,
        "user_name":      user.get("full_name"),
        "overall_status": overall,
        "total_docs":     len(documents),
        "results":        results,
    }


# ── Async wrapper for FastAPI background tasks ────────────────────────────────

async def process_user_documents_async(user_id: int) -> Dict:
    """
    Non-blocking wrapper — runs the synchronous pipeline in a thread pool.
    Uses asyncio.to_thread (not anyio.to_process) so the PaddleOCR singleton
    is shared and never re-initialized between users.
    """
    return await asyncio.to_thread(process_user_documents, user_id)
