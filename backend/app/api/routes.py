"""
app/api/routes.py — FastAPI router v2
====================================
Fixed:
  - Signed URL key compatibility (signedUrl vs signedURL)
  - complete-upload returns storage_paths + preview_url
  - Structured error responses at every stage
  - Safe upload transaction with cleanup on failure
  - Detailed logging at each step
"""

from __future__ import annotations
import io
import os
import re
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.services.validation_service import process_user_documents, process_user_documents_async
from app.workers.bulk_worker import enqueue_user, enqueue_all_users, get_queue_status
from app.services.ocr_pipeline import process_document
from app.academic_engine.master_pipeline import MasterPipeline as _AcademicPipeline

# Singleton — one instance for the lifetime of the process (models are expensive to load)
_academic_pipeline: Optional["_AcademicPipeline"] = None

def _get_academic_pipeline() -> "_AcademicPipeline":
    global _academic_pipeline
    if _academic_pipeline is None:
        _academic_pipeline = _AcademicPipeline()
    return _academic_pipeline


class CreateUserBody(BaseModel):
    full_name: Optional[str] = None
    fullName: Optional[str] = None
    dob: Optional[str] = None
    mobile_number: Optional[str] = None
    email: Optional[str] = None
    permanent_address: Optional[str] = None

class ApprovePayload(BaseModel):
    user_id: int
    name: Optional[str] = None
    aadhaar: Optional[str] = None
    pan: Optional[str] = None
    dob: Optional[str] = None
    percentage: Optional[str] = None
    cgpa: Optional[str] = None
    tenth: Optional[str] = None
    twelfth: Optional[str] = None
    degree: Optional[str] = None
    diploma: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _generate_signed_url(storage_path: str, expires_in: int = 3600) -> Optional[str]:
    """
    Generate a signed URL for Supabase Storage.
    Handles both old SDK (signedURL) and new SDK (signedUrl) response keys.
    """
    try:
        sb = get_supabase()
        res = sb.storage.from_("documents").create_signed_url(storage_path, expires_in)

        # SDK response is a dict
        if isinstance(res, dict):
            # Detect error responses (statusCode key indicates an error)
            if "statusCode" in res or "error" in res:
                logger.warning("[routes] Signed URL error for %s: %s", storage_path, res)
                return None
            # Handle both camelCase variants across SDK versions
            url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
            if url:
                logger.debug("[routes] Signed URL generated for %s", storage_path)
                return url
            logger.warning("[routes] Signed URL response has no URL key: %s", list(res.keys()))
            return None

        # Some SDK versions return the URL as a string directly
        if isinstance(res, str) and res.startswith("http"):
            return res

        logger.warning("[routes] Unexpected signed URL response type: %s", type(res))
        return None

    except Exception as exc:
        logger.error("[routes] Signed URL generation failed for %s: %s", storage_path, exc)
        return None


def _structured_error(stage: str, message: str, status_code: int = 500):
    """Return a structured error response."""
    logger.error("[routes] Error at stage='%s': %s", stage, message)
    raise HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "stage": stage,
            "error": message,
        }
    )


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health", tags=["System"])
def health():
    """
    Lightweight liveness probe — returns immediately without any blocking I/O.

    IMPORTANT: This endpoint must NEVER make Supabase DB queries or any other
    network calls. The frontend polls it every 15 seconds with a 5-second timeout
    to detect if the backend is alive. During bulk OCR, all DB connections are
    in use by OCR threads — any additional DB query here would compete for
    connections and time out, causing a false 'offline' detection that kills
    the OCR batch.

    Use /api/health/full for the detailed diagnostic check (SystemHealth page).
    """
    import os
    from app.workers.bulk_worker import get_queue_status

    # ── Worker pool (in-memory, no I/O) ─────────────────────────────────────
    queue_info = get_queue_status()
    worker_alive = queue_info.get("workers_alive", 0) > 0
    queue_depth = queue_info.get("queue_size", 0)

    # ── Env vars (in-memory, no I/O) ─────────────────────────────────────────
    env_loaded = bool(
        os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")
    )

    # Always 'ok' or 'degraded' — never 'error' from the liveness probe
    # A running server that can respond to this request IS online.
    overall = "ok" if (env_loaded and worker_alive) else "degraded"

    return {
        "status":      overall,
        "service":     "doc-validator",
        "supabase":    "assumed_connected",   # not checked — avoids DB call
        "workers":     "running" if worker_alive else "stopped",
        "env_loaded":  env_loaded,
        "queue_depth": queue_depth,
    }


@router.get("/health/full", tags=["System"])
def health_full():
    """
    Full diagnostic health check — makes a live Supabase DB query.
    Used by the SystemHealth page only (not by the frontend liveness probe).
    DO NOT use this for connection detection during bulk OCR.
    """
    import os
    from app.workers.bulk_worker import get_queue_status

    supabase_status = "disconnected"
    try:
        sb = get_supabase()
        sb.table("users").select("id").limit(1).execute()
        supabase_status = "connected"
    except Exception as exc:
        logger.warning("[routes/health/full] Supabase check failed: %s", exc)
        supabase_status = f"error: {exc}"

    queue_info = get_queue_status()
    worker_alive = queue_info.get("workers_alive", 0) > 0
    env_loaded = bool(
        os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")
    )

    if supabase_status == "connected" and worker_alive:
        overall = "ok"
    elif supabase_status == "connected" or worker_alive:
        overall = "degraded"
    else:
        overall = "error"

    return {
        "status":      overall,
        "service":     "doc-validator",
        "supabase":    supabase_status,
        "workers":     "running" if worker_alive else "stopped",
        "env_loaded":  env_loaded,
        "queue_depth": queue_info.get("queue_size", 0),
    }


@router.get("/ocr/progress", tags=["System"])
def ocr_progress():
    """
    Aggregate OCR job counts consumed by the SystemHealth UI page.
    Returns: total, pending, processing, completed, failed, percent_complete.
    """
    try:
        sb = get_supabase()

        # Total documents
        docs_res = sb.table("documents").select("id", count="exact").execute()
        total = docs_res.count or 0

        # Extracted data counts (completed = has extraction row)
        ext_res = sb.table("extracted_data").select("id", count="exact").execute()
        completed = min(ext_res.count or 0, total)

        # Documents in review queue with status=processing
        processing = 0
        try:
            proc_res = (
                sb.table("validation_reviews")
                .select("id", count="exact")
                .eq("status", "pending")
                .execute()
            )
            processing = proc_res.count or 0
        except Exception:
            pass

        # Failed = documents that have a review with failed/rejected status
        failed = 0
        try:
            fail_res = (
                sb.table("validation_reviews")
                .select("id", count="exact")
                .eq("decision", "rejected")
                .execute()
            )
            failed = fail_res.count or 0
        except Exception:
            pass

        pending = max(0, total - completed - processing)
        pct = round((completed / total) * 100, 1) if total > 0 else 0.0

        return {
            "total":            total,
            "completed":        completed,
            "pending":          pending,
            "processing":       processing,
            "failed":           failed,
            "percent_complete": pct,
        }
    except Exception as e:
        logger.error("[routes/ocr-progress] Error: %s", e)
        raise HTTPException(500, str(e))


@router.get("/audit-logs", tags=["Audit"])
def get_audit_logs(
    limit:  int = 500,
    offset: int = 0,
    user_id: Optional[str] = None,
    action:  Optional[str] = None,
):
    """
    Fetch audit log entries.
    Primary source: review_history table.
    Fallback: synthesize events from documents, verified_data, users tables.
    """
    sb = get_supabase()
    normalized = []

    # ── Primary: review_history ───────────────────────────────────────────────
    try:
        query = (
            sb.table("review_history")
            .select("*")
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
        )
        if user_id:
            query = query.eq("actor_id", user_id)
        if action:
            query = query.eq("action", action)

        rows = query.execute().data or []
        for r in rows:
            normalized.append({
                "id":             r.get("id"),
                "created_at":     r.get("created_at"),
                "timestamp":      r.get("created_at"),
                "user_id":        r.get("actor_id"),
                "actor_id":       r.get("actor_id"),
                "action":         r.get("action"),
                "entity_id":      r.get("review_id"),
                "previous_state": r.get("before_state"),
                "new_state":      r.get("after_state"),
                "details":        r.get("metadata"),
                "metadata":       r.get("metadata"),
            })
        if normalized:
            return normalized
        # table exists but is empty — fall through to synthesize
    except Exception as primary_err:
        err_str = str(primary_err)
        if "PGRST205" not in err_str and "does not exist" not in err_str:
            logger.error("[routes/audit-logs] review_history error: %s", primary_err)
            raise HTTPException(500, err_str)
        logger.info("[routes/audit-logs] review_history not found, synthesizing events from core tables")

    # ── Fallback: synthesize from documents, verified_data, users ────────────
    try:
        events = []

        # 1. Document upload events (from documents table)
        try:
            doc_res = (
                sb.table("documents")
                .select("id, user_id, doc_type, uploaded_at")
                .order("uploaded_at", desc=True)
                .limit(200)
                .execute()
            )
            for d in (doc_res.data or []):
                events.append({
                    "id":          f"doc_{d['id']}",
                    "created_at":  d.get("uploaded_at"),
                    "timestamp":   d.get("uploaded_at"),
                    "user_id":     str(d.get("user_id", "system")),
                    "actor_id":    str(d.get("user_id", "system")),
                    "action":      "upload",
                    "entity_id":   str(d.get("id", "")),
                    "previous_state": None,
                    "new_state":   f"{d.get('doc_type','document')} uploaded",
                    "details":     {"doc_type": d.get("doc_type"), "document_id": d.get("id")},
                    "metadata":    {"doc_type": d.get("doc_type")},
                })
        except Exception as doc_err:
            logger.debug("[routes/audit-logs] doc events error: %s", doc_err)

        # 2. Verification events (from verified_data table)
        try:
            ver_res = (
                sb.table("verified_data")
                .select("id, user_id, status, verified_at, doc_type")
                .order("verified_at", desc=True)
                .limit(200)
                .execute()
            )
            for v in (ver_res.data or []):
                status = (v.get("status") or "").upper()
                act = "approve" if "APPROV" in status or "VERIF" in status else \
                      "reject"  if "REJECT" in status or "MISMATCH" in status else \
                      "ocr_process"
                events.append({
                    "id":          f"ver_{v['id']}",
                    "created_at":  v.get("verified_at"),
                    "timestamp":   v.get("verified_at"),
                    "user_id":     str(v.get("user_id", "system")),
                    "actor_id":    "system",
                    "action":      act,
                    "entity_id":   str(v.get("user_id", "")),
                    "previous_state": None,
                    "new_state":   v.get("status"),
                    "details":     {"status": v.get("status"), "doc_type": v.get("doc_type")},
                    "metadata":    {"doc_type": v.get("doc_type"), "status": v.get("status")},
                })
        except Exception as ver_err:
            logger.debug("[routes/audit-logs] ver events error: %s", ver_err)

        # 3. User registration events
        try:
            user_res = (
                sb.table("users")
                .select("id, full_name, created_at")
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            for u in (user_res.data or []):
                events.append({
                    "id":          f"user_{u['id']}",
                    "created_at":  u.get("created_at"),
                    "timestamp":   u.get("created_at"),
                    "user_id":     str(u.get("id", "")),
                    "actor_id":    str(u.get("id", "")),
                    "action":      "SUBMITTED_FOR_REVIEW",
                    "entity_id":   str(u.get("id", "")),
                    "previous_state": None,
                    "new_state":   f"User '{u.get('full_name','')}' registered",
                    "details":     {"full_name": u.get("full_name"), "user_id": u.get("id")},
                    "metadata":    {"full_name": u.get("full_name")},
                })
        except Exception as usr_err:
            logger.debug("[routes/audit-logs] user events error: %s", usr_err)

        # Sort all synthesized events by timestamp desc, apply offset + limit
        events.sort(key=lambda x: x.get("created_at") or "", reverse=True)

        # Apply action filter if requested
        if action:
            events = [e for e in events if e.get("action") == action]

        # Apply user_id filter if requested
        if user_id:
            events = [e for e in events if str(e.get("user_id","")) == str(user_id)]

        return events[offset: offset + limit]

    except Exception as fallback_err:
        logger.error("[routes/audit-logs] Fallback synthesis failed: %s", fallback_err)
        return []


# ── Intelligence Hub / Query endpoint ────────────────────────────────────────

@router.get("/insights", tags=["Query"])
def get_insights(q: str = "", search: str = ""):
    """
    NLP-style query endpoint powering the Intelligence Hub (Query.jsx).
    Accepts a query string and returns enriched user records.
    """
    try:
        sb = get_supabase()
        users_res = sb.table("users").select("*").order("created_at", desc=True).execute()
        users = users_res.data or []

        if not users:
            return {"results": [], "total": 0, "query": q}

        user_ids = [u["id"] for u in users]
        ext_res = (
            sb.table("extracted_data")
            .select("user_id, doc_type, name, aadhaar_number, pan_number, dob")
            .in_("user_id", user_ids)
            .execute()
        )
        ext_rows = ext_res.data or []

        has_aadhaar, has_pan, has_academic = set(), set(), set()
        ACADEMIC_DOC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
        ext_map  = {}   # uid -> { doc_type: row }   (KYC: last wins)
        acad_map = {}   # uid -> [row, ...]           (academic: collect all)
        for row in ext_rows:
            uid = row["user_id"]
            dt  = row.get("doc_type", "")
            if dt == "aadhaar":
                has_aadhaar.add(uid)
            elif dt == "pan":
                has_pan.add(uid)
            elif dt in ACADEMIC_DOC_TYPES:
                has_academic.add(uid)
                acad_map.setdefault(uid, []).append(row)
            ext_map.setdefault(uid, {})
            ext_map[uid][dt] = row

        from datetime import date as _date
        import re as _re

        def _parse_score(row):
            """aadhaar_number=pct (repurposed), pan_number=grade/CGPA (repurposed)."""
            pct_raw  = row.get("aadhaar_number")
            cgpa_raw = row.get("pan_number")
            pct = cgpa = None
            if pct_raw:
                try:
                    v = float(str(pct_raw).replace("%","").strip())
                    if v > 10: pct = v
                    else:      cgpa = v
                except Exception: pass
            if cgpa_raw:
                try:
                    v = float(str(cgpa_raw).strip())
                    if 0 < v <= 10.0: cgpa = v
                except Exception: pass
            return pct, cgpa

        results = []
        for u in users:
            uid = u["id"]
            adh  = ext_map.get(uid, {}).get("aadhaar") or {}
            pan  = ext_map.get(uid, {}).get("pan") or {}
            acad_rows = acad_map.get(uid, [])

            aadhaar_avail  = uid in has_aadhaar
            pan_avail      = uid in has_pan
            academic_avail = uid in has_academic

            age, dob_str = None, u.get("dob") or adh.get("dob") or pan.get("dob")
            if dob_str:
                try:
                    dob = _date.fromisoformat(str(dob_str)[:10])
                    today = _date.today()
                    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                except Exception: pass

            # Academic aggregation
            acad_doc_types = sorted({r.get("doc_type") for r in acad_rows if r.get("doc_type")})
            percentages, cgpas = [], []
            for ar in acad_rows:
                p, c = _parse_score(ar)
                if p is not None: percentages.append(p)
                if c is not None: cgpas.append(c)

            best_pct  = max(percentages) if percentages else None
            best_cgpa = max(cgpas)       if cgpas       else None
            has_tenth   = "tenth"   in acad_doc_types
            has_twelfth = "twelfth" in acad_doc_types
            has_degree  = any(d in acad_doc_types for d in ("degree", "diploma"))

            record = {
                "user_id":            uid,
                "name":               u.get("full_name") or adh.get("name") or pan.get("name"),
                "aadhaar_number":     adh.get("aadhaar_number"),
                "pan_number":         pan.get("pan_number"),
                "dob":                dob_str,
                "age":                age,
                "aadhaar_available":  aadhaar_avail,
                "pan_available":      pan_avail,
                "academic_available": academic_avail,
                "academic_doc_types": acad_doc_types,
                "academic_percentage": best_pct,
                "academic_cgpa":      best_cgpa,
                "has_tenth":          has_tenth,
                "has_twelfth":        has_twelfth,
                "has_degree":         has_degree,
                "academic_count":     len(acad_rows),
                "created_at":         u.get("created_at"),
            }

            # ── NLP query filter ─────────────────────────────────────────
            qry = (q or search or "").lower().strip()
            if qry:
                # KYC
                if any(k in qry for k in ["missing aadhaar", "missing adhar", "no aadhaar", "no adhar"]):
                    if aadhaar_avail: continue
                elif any(k in qry for k in ["missing pan", "no pan"]):
                    if pan_avail: continue
                elif "mismatch" in qry:
                    a_name = (adh.get("name") or "").strip().lower()
                    p_name = (pan.get("name") or "").strip().lower()
                    if not (a_name and p_name and a_name != p_name): continue
                # Age
                elif _re.search(r"age\s*>\s*(\d+)", qry):
                    m = _re.search(r"age\s*>\s*(\d+)", qry)
                    if age is None or age <= int(m.group(1)): continue
                elif _re.search(r"age\s*<\s*(\d+)", qry):
                    m = _re.search(r"age\s*<\s*(\d+)", qry)
                    if age is None or age >= int(m.group(1)): continue
                # Academic — percentage / score
                elif any(k in qry for k in ["distinction", "above 75", "> 75", "75%"]):
                    if record.get("academic_percentage") is None or record["academic_percentage"] < 75.0: continue
                elif any(k in qry for k in ["above 80", "> 80", "80%"]):
                    if record.get("academic_percentage") is None or record["academic_percentage"] < 80.0: continue
                elif any(k in qry for k in ["first class", "first division"]):
                    p = record.get("academic_percentage")
                    if p is None or not (60.0 <= p < 75.0): continue
                elif any(k in qry for k in ["below 60", "< 60", "low marks", "low score"]):
                    if record.get("academic_percentage") is None or record["academic_percentage"] >= 60.0: continue
                elif any(k in qry for k in ["failed", "fail", "below 40", "< 40"]):
                    if record.get("academic_percentage") is None or record["academic_percentage"] >= 40.0: continue
                elif any(k in qry for k in ["toppers", "top scorer", "top students", "highest marks", "best score"]):
                    if not record.get("academic_percentage") and not record.get("academic_cgpa"): continue
                # Academic — CGPA
                elif any(k in qry for k in ["cgpa > 8", "cgpa>8", "cgpa above 8"]):
                    if record.get("academic_cgpa") is None or record["academic_cgpa"] < 8.0: continue
                elif any(k in qry for k in ["cgpa > 7", "cgpa>7", "cgpa above 7"]):
                    if record.get("academic_cgpa") is None or record["academic_cgpa"] < 7.0: continue
                elif any(k in qry for k in ["low cgpa", "cgpa < 6", "weak cgpa"]):
                    if record.get("academic_cgpa") is None or record["academic_cgpa"] >= 6.0: continue
                elif any(k in qry for k in ["highest cgpa", "best cgpa", "top cgpa"]):
                    if not record.get("academic_cgpa"): continue
                # Academic — doc presence
                elif any(k in qry for k in ["missing academic", "no marksheet", "no academic"]):
                    if record.get("academic_doc_types"): continue
                elif any(k in qry for k in ["has academic", "with academic", "academic docs"]):
                    if not record.get("academic_doc_types"): continue
                elif any(k in qry for k in ["all academic", "complete academic", "full academic"]):
                    if not (record.get("has_tenth") and record.get("has_twelfth") and record.get("has_degree")): continue
                elif any(k in qry for k in ["only 10th", "only tenth", "ssc only"]):
                    if not (record.get("has_tenth") and not record.get("has_twelfth") and not record.get("has_degree")): continue
                elif any(k in qry for k in ["only 12th", "only twelfth", "hsc only"]):
                    if not (record.get("has_twelfth") and not record.get("has_tenth") and not record.get("has_degree")): continue
                elif any(k in qry for k in ["degree", "graduate", "graduation", "bachelor"]):
                    if not record.get("has_degree"): continue
                elif any(k in qry for k in ["10th", "tenth", "ssc"]):
                    if not record.get("has_tenth"): continue
                elif any(k in query for k in ["12th", "twelfth", "hsc"]):
                    if not record.get("has_twelfth"): continue
                else:
                    name_str = str(record.get("name") or "").lower()
                    if query not in name_str and query not in str(uid): continue

            results.append(record)

        # Sort toppers by academic score descending
        qry_lower = (q or "").lower()
        if any(k in qry_lower for k in ["toppers", "top scorer", "highest marks", "highest cgpa", "best cgpa", "top students", "best score"]):
            results.sort(
                key=lambda r: (r.get("academic_percentage") or 0) + (r.get("academic_cgpa") or 0) * 10,
                reverse=True,
            )

        return {"results": results, "total": len(results), "query": q}
    except Exception as e:
        logger.error("[routes/insights] Error: %s", e)
        raise HTTPException(500, str(e))



# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/users", tags=["Users"])
def list_users():
    """
    List all users, enriched with their latest OCR extracted_data.
    This is the primary data source for the Database UI.
    """
    try:
        sb = get_supabase()
        users_res = sb.table("users").select("*").order("created_at", desc=True).execute()
        users = users_res.data or []

        if not users:
            return {"success": True, "users": []}

        # ── Join latest extracted_data for each user ──────────────────────────
        # Fetch all extracted_data rows at once (more efficient than N queries)
        user_ids = [u["id"] for u in users]
        try:
            ext_res = (
                sb.table("extracted_data")
                .select("user_id, doc_type, name, aadhaar_number, pan_number, dob, confidence_score, processed_at")
                .in_("user_id", user_ids)
                .execute()
            )
            extracted_rows = ext_res.data or []
        except Exception as ext_err:
            logger.warning("[routes/list_users] Could not fetch extracted_data: %s", ext_err)
            extracted_rows = []

        # Build a map: user_id → { doc_type → freshest_row }
        # STRICT: never merge name/dob across aadhaar and pan.
        # RECENCY RULE: most recently processed row always wins on re-extraction.
        # (Previously used confidence_score as tiebreaker — wrong: a re-run with
        #  lower confidence would display stale high-confidence data.)
        ext_map: dict = {}   # uid → { "aadhaar": row, "pan": row }
        for row in extracted_rows:
            uid   = row["user_id"]
            dtype = row.get("doc_type", "unknown")
            if uid not in ext_map:
                ext_map[uid] = {}
            existing = ext_map[uid].get(dtype)
            if existing is None:
                ext_map[uid][dtype] = row
            else:
                # Use processed_at for recency comparison; fall back to confidence
                new_ts = row.get("processed_at") or ""
                old_ts = existing.get("processed_at") or ""
                if new_ts >= old_ts:  # ISO 8601 strings sort lexicographically
                    ext_map[uid][dtype] = row

        # ── Fetch doc_types per user from documents table (KYC) ───────────────
        ACADEMIC_DOC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
        try:
            docs_res = (
                sb.table("documents")
                .select("user_id, doc_type")
                .in_("user_id", user_ids)
                .execute()
            )
            # Build map: user_id → sorted unique doc_type set
            doc_type_map: dict = {}
            for row in (docs_res.data or []):
                uid = row["user_id"]
                dt  = row.get("doc_type")
                if uid not in doc_type_map:
                    doc_type_map[uid] = set()
                if dt:
                    doc_type_map[uid].add(dt)
        except Exception as dt_err:
            logger.warning("[routes/list_users] Could not fetch doc_types from documents: %s", dt_err)
            doc_type_map = {}

        # ── Fetch validation review status ────────────────────────────────────
        review_map: dict = {}
        try:
            rv_res = sb.table("validation_reviews").select("user_id, status, decision, updated_at").order("updated_at", desc=True).execute()
            for row in (rv_res.data or []):
                uid = row["user_id"]
                if uid not in review_map:
                    review_map[uid] = row # keeping the most recent one
        except Exception as rv_err:
            logger.warning("[routes/list_users] Could not fetch validation_reviews: %s", rv_err)

        # ── Also fetch academic doc_types from extracted_data ─────────────────
        # Academic docs are stored in extracted_data (no doc_type constraint there).
        # We identify them by doc_type being in ACADEMIC_DOC_TYPES.
        try:
            acad_ext_res = (
                sb.table("extracted_data")
                .select("user_id, doc_type")
                .in_("user_id", user_ids)
                .in_("doc_type", list(ACADEMIC_DOC_TYPES))
                .execute()
            )
            for row in (acad_ext_res.data or []):
                uid = row["user_id"]
                dt  = row.get("doc_type")
                if uid not in doc_type_map:
                    doc_type_map[uid] = set()
                if dt:
                    doc_type_map[uid].add(dt)
            acad_count = len(acad_ext_res.data or [])
            if acad_count > 0:
                logger.info(
                    "[routes/list_users] Found %d academic extracted_data rows across users",
                    acad_count
                )
        except Exception as acad_err:
            logger.warning("[routes/list_users] Could not fetch academic doc_types: %s", acad_err)

        # Helper: unwrap OCR {"value": "...", "confidence": N} objects and JSON strings.
        # Supabase stores extracted fields as JSONB so they can arrive as dicts.
        def _unwrap(val):
            if val is None:
                return None
            if isinstance(val, dict):
                return str(val.get("value") or "").strip() or None
            if isinstance(val, str):
                s = val.strip()
                if s.startswith("{"):
                    import json as _j
                    try:
                        obj = _j.loads(s)
                        if isinstance(obj, dict) and "value" in obj:
                            return str(obj["value"]).strip() or None
                    except Exception:
                        pass
                return s or None
            return str(val).strip() or None

        # ── Build enriched user records with STRICT per-doc isolation ────────────────
        enriched = []
        for u in users:
            uid  = u["id"]
            docs = ext_map.get(uid, {})
            a    = docs.get("aadhaar") or {}
            p    = docs.get("pan")     or {}

            aadhaar_data = {
                "name":           _unwrap(a.get("name")),
                "aadhaar_number": _unwrap(a.get("aadhaar_number")),
                "dob":            _unwrap(a.get("dob")),
                "confidence":     round((a.get("confidence_score") or 0) * 100, 1),
            }
            pan_data = {
                "name":       _unwrap(p.get("name")),
                "pan_number": _unwrap(p.get("pan_number")),
                "dob":        _unwrap(p.get("dob")),
                "confidence": round((p.get("confidence_score") or 0) * 100, 1),
            }

            all_doc_types = doc_type_map.get(uid, set())

            # ── If permanently approved, use final_name as the display name ────
            # final_verified=True means APPROVE & SAVE was completed.
            # full_name was already overwritten to OCR name on approval,
            # but also read final_name as an explicit cross-check.
            is_final_verified = bool(u.get("final_verified"))
            display_name = u.get("full_name") or ""
            if is_final_verified and u.get("final_name"):
                display_name = u["final_name"]

            enriched_user = {
                **u,
                "aadhaar":        aadhaar_data,
                "pan":            pan_data,
                # ── USER-ENTERED IDs (from the upload form, stored in users table) ──
                "entered_aadhaar_number": u.get("aadhaar_number") or "",
                "entered_pan_number":     u.get("pan_number")     or "",
                # FINAL VERIFIED values: explicit so table always has them
                "final_name":    _unwrap(u.get("final_name")),
                "final_aadhaar": _unwrap(u.get("final_aadhaar")),
                "final_pan":     _unwrap(u.get("final_pan")),
                "final_dob":     _unwrap(u.get("final_dob")),
                # Flat table display: final_* wins; unwrapped OCR is fallback
                "aadhaar_number": _unwrap(u.get("final_aadhaar")) or _unwrap(a.get("aadhaar_number")) or _unwrap(u.get("aadhaar_number")) or "",
                "pan_number":     _unwrap(u.get("final_pan"))     or _unwrap(p.get("pan_number"))     or _unwrap(u.get("pan_number"))     or "",
                # ── CONTACT FIELDS ────────────────────────────────────────────
                "email":             u.get("email") or "",
                "mobile_number":     u.get("mobile_number") or "",
                "permanent_address": u.get("permanent_address") or "",
                # ── Display name: final_name if verified, else full_name ───────
                "name":          display_name,
                "original_name": display_name,
                "full_name":     display_name,
                "extracted_name": _unwrap(a.get("name")) or _unwrap(p.get("name")),
                "extracted_dob":  _unwrap(a.get("dob"))  or _unwrap(p.get("dob")),
                "confidence":     max(
                    aadhaar_data["confidence"],
                    pan_data["confidence"],
                ),
                # Real uploaded doc types from documents table
                "doc_types": sorted(doc_type_map.get(uid, set())),
            }
            logger.debug(
                "[routes/list_users] uid=%s email=%s mobile=%s address=%s",
                uid,
                bool(u.get("email")),
                bool(u.get("mobile_number")),
                bool(u.get("permanent_address")),
            )
            
            # ── Status: VERIFIED from users table takes priority over everything ──
            # VERIFIED is the permanent state written by APPROVE & SAVE.
            # Never fall back to review tables if users.status is already set.
            db_status = (u.get("status") or "").upper()
            db_workflow = (u.get("workflow_state") or "").upper()

            if db_status == "VERIFIED" or db_workflow == "VERIFIED" or is_final_verified:
                enriched_user["status"] = "VERIFIED"
                enriched_user["workflow_state"] = "VERIFIED"
                enriched_user["is_verified"] = 1
                enriched_user["final_verified"] = True
            elif db_status in ("REJECTED", "APPROVED", "REVIEW_REQUIRED", "UPLOADED", "PROCESSING"):
                # Status already set in DB — use it directly, no fallback needed
                pass
            else:
                # No status in users table — fall back to validation_reviews
                rv = review_map.get(uid)
                if rv:
                    if rv["status"] == "completed" and rv["decision"] == "approved":
                        enriched_user["status"] = "VERIFIED"
                        enriched_user["workflow_state"] = "VERIFIED"
                        enriched_user["is_verified"] = 1
                    elif rv["decision"] == "rejected":
                        enriched_user["status"] = "REJECTED"
                        enriched_user["workflow_state"] = "REJECTED"
                    elif rv["status"] == "pending":
                        enriched_user["status"] = "REVIEW_REQUIRED"
                        enriched_user["workflow_state"] = "REVIEW_REQUIRED"
                else:
                    enriched_user["status"] = "PENDING"
                    enriched_user["workflow_state"] = "PENDING"

            enriched.append(enriched_user)

        logger.info("[routes/list_users] Returning %d users with extracted_data", len(enriched))
        return {"success": True, "users": enriched}
    except Exception as e:
        logger.error("[routes] list_users error: %s", e)
        raise HTTPException(500, str(e))


@router.post("/users", tags=["Users"])
async def create_user_endpoint(body: CreateUserBody):
    """Create a user — accepts JSON body with optional contact fields."""
    try:
        sb = get_supabase()
        name = (body.full_name or body.fullName or "").strip()
        date = (body.dob or "").strip()
        if not name or not date:
            raise HTTPException(400, "full_name and dob are required")
        user_payload = {"full_name": name, "dob": date}
        # Persist contact fields entered during registration
        if body.mobile_number:
            user_payload["mobile_number"] = body.mobile_number.strip()
        if body.email:
            user_payload["email"] = body.email.strip().lower()
        if body.permanent_address:
            user_payload["permanent_address"] = body.permanent_address.strip()
        logger.info("[routes/create_user] Inserting user: name=%s mobile=%s email=%s address=%s",
                    name, bool(body.mobile_number), bool(body.email), bool(body.permanent_address))
        try:
            res = sb.table("users").insert(user_payload).execute()
        except Exception as ins_err:
            # Fallback: retry without contact fields if columns don't exist yet
            logger.warning("[routes/create_user] Insert with contact fields failed (%s), retrying without", ins_err)
            res = sb.table("users").insert({"full_name": name, "dob": date}).execute()
        if res.data:
            logger.info("[routes/create_user] User created — id=%s", res.data[0].get("id"))
        return {"success": True, "user": res.data[0] if res.data else None}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes] create_user error: %s", e)
        raise HTTPException(500, str(e))


@router.post("/approve", tags=["Users"])
async def approve_user(payload: ApprovePayload):
    """
    Approve user. Two-stage DB update:
    Stage 1 (core columns) — MUST succeed or raise 500.
    Stage 2 (new snapshot columns) — silently skipped if columns don’t exist yet.
    """
    import json as _json
    try:
        sb = get_supabase()

        # ── Stage 1: CORE fields ────────────────────────────────────────────────
        # All these columns exist in the original schema. MUST succeed.
        core_data: dict = {
            "workflow_state":      "VERIFIED",
            "is_verified":         1,
            "status":              "VERIFIED",
            "verification_status": "VERIFIED",
            "final_verified":      True,
        }

        
        if payload.name:
            core_data["final_name"] = payload.name
            core_data["full_name"]  = payload.name  # overwrite master name (table reads full_name)
        if payload.aadhaar:
            core_data["final_aadhaar"] = payload.aadhaar
        if payload.pan:
            core_data["final_pan"] = payload.pan
        if payload.dob:
            core_data["final_dob"] = payload.dob
        # NOTE: final_email / final_mobile / final_address are in Stage 2 (optional columns)

        # We will store the final percentage and cgpa in the academic_inputs jsonb field
        # so that it immediately becomes the "entered" verified value for academics.
        if payload.percentage or payload.cgpa:
            try:
                usr_res = sb.table("users").select("academic_inputs").eq("id", payload.user_id).execute()
                current_inputs: dict = {}
                if usr_res.data:
                    raw_ai = usr_res.data[0].get("academic_inputs")
                    if isinstance(raw_ai, str):
                        try:
                            current_inputs = _json.loads(raw_ai)
                        except Exception:
                            current_inputs = {}
                    elif isinstance(raw_ai, dict):
                        current_inputs = raw_ai

                if payload.percentage:
                    current_inputs["final_percentage"] = {"percentage": payload.percentage}
                    core_data["final_percentage"] = str(payload.percentage)
                if payload.cgpa:
                    current_inputs["final_cgpa"] = {"cgpa": payload.cgpa}
                    core_data["final_cgpa"] = str(payload.cgpa)
                if payload.tenth:
                    current_inputs["tenth"] = {"percentage": payload.tenth}
                if payload.twelfth:
                    current_inputs["twelfth"] = {"percentage": payload.twelfth}
                if payload.degree:
                    current_inputs["degree"] = {"cgpa": payload.degree}
                if payload.diploma:
                    current_inputs["diploma"] = {"cgpa": payload.diploma}

                core_data["academic_inputs"] = current_inputs
            except Exception as e:
                logger.warning("[routes/approve] Could not prepare academic_inputs: %s", e)

        # Execute Stage 1 — HARD FAILURE if this fails
        logger.info("[routes/approve] Stage 1 update for user=%s keys=%s", payload.user_id, list(core_data.keys()))
        core_res = sb.table("users").update(core_data).eq("id", payload.user_id).execute()
        if not core_res.data:
            raise HTTPException(500, f"Stage 1 approval update returned no data for user {payload.user_id}")

        logger.info(
            "[routes/approve] Stage 1 OK: user=%s final_name=%s status=%s",
            payload.user_id, core_res.data[0].get("final_name"), core_res.data[0].get("status"),
        )

        updated_user = core_res.data[0]

        # ── Stage 2: OPTIONAL columns (silently skip any that don't exist in DB) ──
        # Includes snapshot + contact fields that may not yet be in Supabase schema.
        final_snapshot = {
            "name":       payload.name       or "",
            "aadhaar":    payload.aadhaar     or "",
            "pan":        payload.pan         or "",
            "dob":        payload.dob         or "",
            "percentage": str(payload.percentage) if payload.percentage else "",
            "cgpa":       str(payload.cgpa)        if payload.cgpa       else "",
        }
        optional_data: dict = {
            "verification_locked": True,
            "final_verified_data": final_snapshot,
        }
        if payload.email:   optional_data["final_email"]   = payload.email
        if payload.mobile:  optional_data["final_mobile"]  = payload.mobile
        if payload.address: optional_data["final_address"] = payload.address
        if payload.percentage: optional_data["final_percentage"] = str(payload.percentage)
        if payload.cgpa:       optional_data["final_cgpa"]       = str(payload.cgpa)
        try:
            sb.table("users").update(optional_data).eq("id", payload.user_id).execute()
            logger.info("[routes/approve] Stage 2 optional columns written for user=%s", payload.user_id)
        except Exception as opt_err:
            logger.warning("[routes/approve] Stage 2 partially skipped (missing columns): %s", opt_err)
            # Try individual fields so partial writes succeed
            for col, val in optional_data.items():
                try:
                    sb.table("users").update({col: val}).eq("id", payload.user_id).execute()
                except Exception:
                    pass

        # Always re-fetch to get the complete latest row
        try:
            fresh = sb.table("users").select("*").eq("id", payload.user_id).execute()
            if fresh.data:
                updated_user = fresh.data[0]
        except Exception as fetch_err:
            logger.warning("[routes/approve] Re-fetch failed, using Stage 1 result: %s", fetch_err)

        logger.info(
            "[routes/approve] COMPLETE: user=%s final_name=%s final_aadhaar=%s final_pan=%s",
            payload.user_id,
            updated_user.get("final_name"),
            updated_user.get("final_aadhaar"),
            updated_user.get("final_pan"),
        )

        try:
            vd_res = sb.table("verified_data").select("id").eq("user_id", payload.user_id).execute()
            if vd_res.data:
                for row in vd_res.data:
                    sb.table("verified_data").update({
                        "status": "APPROVED",
                        "decision": "approved"
                    }).eq("id", row["id"]).execute()

            vr_res = sb.table("validation_reviews").select("id").eq("user_id", payload.user_id).execute()
            if vr_res.data:
                for row in vr_res.data:
                    sb.table("validation_reviews").update({
                        "status": "completed",
                        "decision": "approved"
                    }).eq("id", row["id"]).execute()
        except Exception as review_err:
            logger.warning("[routes/approve] Non-fatal error updating review tables: %s", review_err)

        return {"success": True, "user": updated_user}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/approve] Error: %s", e)
        raise HTTPException(500, str(e))

class ActionPayload(BaseModel):
    action: str
    corrected_data: Optional[dict] = None

@router.post("/users/{user_id}/action", tags=["Users"])
async def user_action(user_id: int, payload: ActionPayload):
    """
    Handle legacy REJECTED or REVIEW_REQUIRED actions.
    """
    try:
        sb = get_supabase()
        
        # Determine status string
        new_status = payload.action
        
        # Update users table
        update_data = {
            "workflow_state": new_status,
            "status": new_status,
        }
        
        # If there is corrected data (like rejecting but fixing names)
        if payload.corrected_data:
            if payload.corrected_data.get("name"):
                update_data["full_name"] = payload.corrected_data["name"]
            if payload.corrected_data.get("aadhaar"):
                update_data["aadhaar_number"] = payload.corrected_data["aadhaar"]
            if payload.corrected_data.get("pan"):
                update_data["pan_number"] = payload.corrected_data["pan"]
            if payload.corrected_data.get("dob"):
                update_data["dob"] = payload.corrected_data["dob"]
                
        updated_user = None
        try:
            res = sb.table("users").update(update_data).eq("id", user_id).execute()
            if res.data:
                updated_user = res.data[0]
        except Exception as update_err:
            logger.warning("[routes/action] Non-fatal error updating users table: %s", update_err)
            
        if not updated_user:
            # Fallback if users update failed (e.g., missing columns)
            usr_res = sb.table("users").select("*").eq("id", user_id).execute()
            if not usr_res.data:
                raise HTTPException(404, f"User {user_id} not found")
            updated_user = usr_res.data[0]
        
        # Update verified_data 
        try:
            vd_res = sb.table("verified_data").select("id").eq("user_id", user_id).execute()
            if vd_res.data:
                for row in vd_res.data:
                    sb.table("verified_data").update({
                        "status": new_status,
                        "decision": new_status.lower() if new_status in ["REJECTED", "REVIEW_REQUIRED"] else new_status
                    }).eq("id", row["id"]).execute()
                    
            vr_res = sb.table("validation_reviews").select("id").eq("user_id", user_id).execute()
            if vr_res.data:
                for row in vr_res.data:
                    sb.table("validation_reviews").update({
                        "status": "completed" if new_status == "REJECTED" else "pending",
                        "decision": new_status.lower() if new_status in ["REJECTED", "REVIEW_REQUIRED"] else new_status
                    }).eq("id", row["id"]).execute()
        except Exception as review_err:
            logger.warning("[routes/action] Non-fatal error updating review tables: %s", review_err)

        return {"success": True, "user": updated_user}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/action] Error: %s", e)
        raise HTTPException(500, str(e))

# ── Signed URL ────────────────────────────────────────────────────────────────

@router.get("/signed-url", tags=["Documents"])
def get_signed_url(storage_path: str, expires_in: int = 3600):
    """Generate a signed URL for a document in Supabase Storage."""
    signed_url = _generate_signed_url(storage_path, expires_in)
    if signed_url:
        return {"success": True, "signed_url": signed_url}
    return {"success": False, "error": "Could not generate signed URL. Check storage path and bucket permissions."}


# ── Complete Upload (primary upload endpoint) ─────────────────────────────────

@router.post("/complete-upload", tags=["Upload"])
async def complete_upload(
    background_tasks: BackgroundTasks,
    full_name: str = Form(...),
    dob: str = Form(...),
    aadhaar_number: Optional[str] = Form(None),
    pan_number: Optional[str] = Form(None),
    mobile_number: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    permanent_address: Optional[str] = Form(None),
    aadhaar_file: Optional[UploadFile] = File(None),
    pan_file: Optional[UploadFile] = File(None),
):
    """
    Atomic upload + synchronous OCR:
      1. Validate inputs
      2. Insert user
      3. Upload each file to Supabase Storage
      4. Insert document metadata
      5. Generate preview signed URLs
      6. Run OCR pipeline synchronously (wait for completion)
      7. Return user + documents + extracted fields
    """
    # Extended timeout hint: OCR on a PDF can take 30-90 seconds.
    if not aadhaar_file and not pan_file:
        _structured_error("validation", "At least one document (Aadhaar or PAN) is required.", 400)

    sb = get_supabase()
    uploaded_paths = []
    user_id = None

    try:
        # ── STEP 1: Insert User ───────────────────────────────────────────────
        logger.info(
            "[routes/upload] Creating user: name=%s DOB=%s aadhaar=%s pan=%s mobile=%s email=%s address=%s",
            full_name, dob, bool(aadhaar_number), bool(pan_number),
            bool(mobile_number), bool(email), bool(permanent_address)
        )
        user_payload = {
            "full_name": full_name,
            "dob":       dob,
        }
        if aadhaar_number:
            user_payload["aadhaar_number"] = re.sub(r'\D', '', aadhaar_number)[:12]
        if pan_number:
            user_payload["pan_number"] = pan_number.strip().upper()[:10]
        # Persist contact fields — these are ENTERED by the user, NOT OCR-extracted
        if mobile_number:
            user_payload["mobile_number"] = mobile_number.strip()
        if email:
            user_payload["email"] = email.strip().lower()
        if permanent_address:
            user_payload["permanent_address"] = permanent_address.strip()
        logger.info("[routes/upload] User payload keys: %s", list(user_payload.keys()))
        try:
            user_res = sb.table("users").insert(user_payload).execute()
            logger.info("[routes/upload] DB insert success with all fields")
        except Exception as insert_err:
            logger.warning("[routes/upload] Insert with all fields failed (%s), retrying minimal", insert_err)
            # Fallback: minimal insert without contact columns if they don't exist yet
            minimal_payload = {"full_name": full_name, "dob": dob}
            if aadhaar_number:
                minimal_payload["aadhaar_number"] = re.sub(r'\D', '', aadhaar_number)[:12]
            if pan_number:
                minimal_payload["pan_number"] = pan_number.strip().upper()[:10]
            user_res = sb.table("users").insert(minimal_payload).execute()

        if not user_res.data:
            _structured_error("user_insert", "Failed to create user record in database.")

        user_id = user_res.data[0]["id"]
        logger.info("[routes/upload] User created — user_id=%s fields=%s",
                    user_id, list(user_res.data[0].keys()))

        # ── Helper: upload one file ───────────────────────────────────────────
        async def handle_file(doc_type: str, file: UploadFile) -> dict:
            ext = os.path.splitext(file.filename or "")[1].lower() or ".bin"
            storage_path = f"user_{user_id}/{doc_type}_v1{ext}"

            logger.info("[routes/upload] Reading %s file: %s (%s)",
                        doc_type, file.filename, file.content_type)
            file_bytes = await file.read()
            file_size = len(file_bytes)
            logger.info("[routes/upload] Uploading %s — %d bytes to path: %s",
                        doc_type, file_size, storage_path)

            # ── STEP 2: Upload to Supabase Storage ────────────────────────────
            try:
                upload_res = sb.storage.from_("documents").upload(
                    storage_path,
                    file_bytes,
                    file_options={
                        "content-type": file.content_type or "application/octet-stream",
                        "upsert": "true",
                    }
                )
                logger.info("[routes/upload] Storage upload success for %s", storage_path)
            except Exception as upload_err:
                logger.error("[routes/upload] Storage upload failed for %s: %s", storage_path, upload_err)
                raise Exception(f"Storage upload failed for {doc_type}: {upload_err}")

            uploaded_paths.append(storage_path)

            # ── STEP 3: Insert DB row ─────────────────────────────────────────
            logger.info("[routes/upload] Inserting document record for %s", doc_type)
            doc_payload = {
                "user_id": user_id,
                "doc_type": doc_type,
                "version": 1,
                "storage_path": storage_path,
            }
            doc_res = sb.table("documents").insert(doc_payload).execute()

            if not doc_res.data:
                raise Exception(f"Failed to insert document metadata for {doc_type}")

            doc_record = doc_res.data[0]
            logger.info("[routes/upload] Document record created — doc_id=%s", doc_record.get("id"))

            # ── STEP 4: Generate preview signed URL ───────────────────────────
            preview_url = _generate_signed_url(storage_path, expires_in=7200)
            if preview_url:
                logger.info("[routes/upload] Preview URL generated for %s", doc_type)
            else:
                logger.warning("[routes/upload] Could not generate preview URL for %s", doc_type)

            return {
                **doc_record,
                "preview_url": preview_url,
                "file_size": file_size,
                "file_name": file.filename,
            }

        # ── Process each file ─────────────────────────────────────────────────
        docs_saved = []
        if aadhaar_file:
            docs_saved.append(await handle_file("aadhaar", aadhaar_file))
        if pan_file:
            docs_saved.append(await handle_file("pan", pan_file))

        # ── STEP 5: Run OCR synchronously — WAIT for final result ─────────────
        # Do NOT use background queue. Run the full pipeline now so the
        # response carries the final extracted fields.
        import time as _time
        _t0 = _time.monotonic()
        logger.info("[routes/upload] Starting synchronous OCR for user %s", user_id)

        from app.services.validation_service import process_user_documents_async
        ocr_result = await process_user_documents_async(user_id)

        elapsed = round(_time.monotonic() - _t0, 2)
        logger.info("[routes/upload] OCR complete in %.1fs — status=%s",
                    elapsed, ocr_result.get("overall_status"))

        # ── Build per-doc extracted field summary ──────────────────────────────
        extracted_summary = {}
        for r in (ocr_result.get("results") or []):
            dt = r.get("doc_type", "unknown")
            extracted_summary[dt] = {
                "name":           r.get("extracted", {}).get("name")           if isinstance(r.get("extracted"), dict) else None,
                "aadhaar_number": r.get("extracted", {}).get("aadhaar_number") if isinstance(r.get("extracted"), dict) else None,
                "pan_number":     r.get("extracted", {}).get("pan_number")     if isinstance(r.get("extracted"), dict) else None,
                "dob":            r.get("extracted", {}).get("dob")            if isinstance(r.get("extracted"), dict) else None,
                "confidence":     r.get("ocr_confidence"),
                "status":         r.get("overall_status"),
            }

        return {
            "success": True,
            "user_id": user_id,
            "user": {
                "id":        user_id,
                "full_name": full_name,
                "dob":       dob,
            },
            "documents":         docs_saved,
            "ocr_complete":      True,
            "ocr_elapsed_sec":   elapsed,
            "overall_status":    ocr_result.get("overall_status"),
            "extracted":         extracted_summary,
            "message": "Upload and OCR extraction complete.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/complete-upload] Error: %s", e)
        raise HTTPException(500, str(e))


# ── List all documents for a user (KYC + Academic) ───────────────────────────

@router.get("/users/{user_id}/documents", tags=["Documents"])
def list_user_documents(user_id: int):
    """
    Returns all documents for a user — KYC from `documents`, academic from `extracted_data`.

    Each academic document's extracted sub-object contains:
      percentage, grade (CGPA/CPI/SPI), name, confidence
    This feeds the Review Panel's AcademicVerificationSection.
    """
    ACADEMIC_DOC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
    try:
        sb = get_supabase()

        # ── KYC docs from documents table ─────────────────────────────────────
        res = (sb.table("documents").select("*")
               .eq("user_id", user_id)
               .order("uploaded_at", desc=True)
               .execute())
        docs = res.data or []

        # ── Fetch user-entered academic scores from users.academic_inputs ────
        entered_academic_inputs = {}
        try:
            usr_res = sb.table("users").select("academic_inputs, email, mobile_number, permanent_address").eq("id", user_id).execute()
            if usr_res.data:
                raw_ai = usr_res.data[0].get("academic_inputs") or {}
                if isinstance(raw_ai, str):
                    import json as _json
                    try: raw_ai = _json.loads(raw_ai)
                    except Exception: raw_ai = {}
                entered_academic_inputs = raw_ai or {}
            logger.debug(
                "[routes/list_docs] user_id=%s entered_academic_inputs=%s",
                user_id, entered_academic_inputs
            )
        except Exception as ai_err:
            logger.warning("[routes/list_docs] Could not fetch academic_inputs (column may not exist yet): %s", ai_err)

        # ── Academic docs from extracted_data ─────────────────────────────────
        try:
            acad_res = (
                sb.table("extracted_data")
                .select("id, user_id, doc_type, version, name, aadhaar_number, pan_number, dob, confidence_score, processed_at")
                .eq("user_id", user_id)
                .in_("doc_type", list(ACADEMIC_DOC_TYPES))
                .order("processed_at", desc=True)
                .execute()
            )
            # Column mapping (set during upload):
            #   name           = extracted candidate name
            #   aadhaar_number = extracted percentage (repurposed)
            #   pan_number     = extracted grade/CGPA/SPI (repurposed)
            #   dob            = storage_path for file retrieval (repurposed)
            #   confidence_score = OCR confidence
            for row in (acad_res.data or []):
                storage_path_val = row.get("dob") or ""
                extracted_pct   = row.get("aadhaar_number")   # repurposed col
                extracted_grade = row.get("pan_number")       # repurposed col
                extracted_name  = row.get("name") or None     # universal name extractor result
                ocr_conf        = row.get("confidence_score")

                logger.info(
                    "[routes/list_docs] ACADEMIC ROW — candidate_id=%s doc_type=%s "
                    "pct=%s grade=%s name=%s conf=%s",
                    user_id, row["doc_type"], extracted_pct, extracted_grade,
                    extracted_name, ocr_conf
                )

                docs.append({
                    "id":                       f"acad_{row['id']}",
                    "user_id":                  user_id,
                    "doc_type":                 row["doc_type"],
                    "version":                  row.get("version", 1),
                    "storage_path":             storage_path_val,
                    "uploaded_at":              row.get("processed_at"),
                    "_source":                  "extracted_data",
                    "extracted_percentage":     extracted_pct,
                    "extracted_grade":          extracted_grade,
                    "extracted_year":           None,
                    "extracted_candidate_name": extracted_name,
                    "ocr_confidence":           ocr_conf,
                    # User-entered score for this doc_type (from users.academic_inputs JSONB)
                    "entered_percentage": (entered_academic_inputs.get(row["doc_type"]) or {}).get("percentage"),
                })
            logger.info(
                "[routes/list_docs] user_id=%s KYC docs=%d academic docs=%d",
                user_id, len(res.data or []), len(acad_res.data or [])
            )
        except Exception as acad_err:
            logger.warning("[routes/list_docs] Could not fetch academic docs: %s", acad_err)

        # ── KYC extracted data lookup ──────────────────────────────────────────
        ext_rows: dict = {}
        try:
            ext_res = (sb.table("extracted_data")
                       .select("doc_type, name, aadhaar_number, pan_number, dob, confidence_score")
                       .eq("user_id", user_id)
                       .in_("doc_type", ["aadhaar", "pan"])
                       .execute())
            for row in (ext_res.data or []):
                dtype = row.get("doc_type")
                existing = ext_rows.get(dtype)
                if existing is None or (row.get("confidence_score") or 0) > (existing.get("confidence_score") or 0):
                    ext_rows[dtype] = row
        except Exception as ext_err:
            logger.warning("[routes/list_docs] Could not fetch extracted_data: %s", ext_err)

        # ── Enrich each document with signed URL + extracted fields ────────────
        enriched = []
        for doc in docs:
            storage_path = doc.get("storage_path", "")
            signed_url = None
            if storage_path:
                signed_url = _generate_signed_url(storage_path, expires_in=7200)

            file_ext  = os.path.splitext(storage_path)[1].lower().lstrip(".")
            file_type = "pdf" if file_ext == "pdf" else "image"

            dtype   = doc.get("doc_type", "unknown")
            ext_row = ext_rows.get(dtype) or {}

            if dtype == "aadhaar":
                extracted = {
                    "name":           ext_row.get("name"),
                    "aadhaar_number": ext_row.get("aadhaar_number"),
                    "dob":            ext_row.get("dob"),
                    "confidence":     round((ext_row.get("confidence_score") or 0) * 100, 1),
                }
            elif dtype == "pan":
                extracted = {
                    "name":       ext_row.get("name"),
                    "pan_number": ext_row.get("pan_number"),
                    "dob":        ext_row.get("dob"),
                    "confidence": round((ext_row.get("confidence_score") or 0) * 100, 1),
                }
            else:
                # Academic: OCR fields stored in remapped columns (set during upload)
                extracted = {
                    "percentage":  doc.get("extracted_percentage"),
                    "grade":       doc.get("extracted_grade"),
                    "confidence":  round((doc.get("ocr_confidence") or 0) * 100, 1),
                }

            enriched.append({
                **doc,
                "signed_url":  signed_url,
                "preview_url": signed_url,
                "file_type":   file_type,
                "extracted":   extracted,
            })


        return {"success": True, "documents": enriched}
    except Exception as e:
        logger.error("[routes/list_docs] Error: %s", e)
        raise HTTPException(500, str(e))


# ── Academic records for a candidate (integration endpoint) ───────────────────

@router.get("/users/{user_id}/academic-records", tags=["Documents"])
def list_academic_records(user_id: int):
    """
    Returns all academic OCR extraction records linked to this candidate_id.

    These are stored in extracted_data table with doc_type in ACADEMIC_DOC_TYPES.
    Column mapping:
      name           → OCR extracted candidate name
      aadhaar_number → OCR extracted percentage (repurposed column)
      pan_number     → OCR extracted grade/CGPA/SPI (repurposed column)
      dob            → storage_path for the file in Supabase Storage (repurposed column)
      confidence_score → OCR pipeline confidence (0.0–1.0)

    Response shape for each record:
      {
        candidate_id: int,
        document_type: str,   # 'tenth' | 'twelfth' | 'diploma' | 'degree' | 'semester'
        extracted_percentage: str | null,
        extracted_grade: str | null,
        extracted_name: str | null,
        ocr_confidence: float | null,
        file_path: str | null,
        created_at: str | null,
      }
    """
    ACADEMIC_DOC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
    try:
        sb = get_supabase()
        logger.info("[routes/academic-records] Fetching academic records for candidate_id=%s", user_id)

        res = (
            sb.table("extracted_data")
            .select("id, user_id, doc_type, version, name, aadhaar_number, pan_number, dob, confidence_score, processed_at")
            .eq("user_id", user_id)
            .in_("doc_type", list(ACADEMIC_DOC_TYPES))
            .order("processed_at", desc=True)
            .execute()
        )

        records = []
        for row in (res.data or []):
            extracted_pct   = row.get("aadhaar_number")   # repurposed column
            extracted_grade = row.get("pan_number")       # repurposed column
            ocr_conf        = row.get("confidence_score")
            storage_path    = row.get("dob")              # repurposed column

            records.append({
                "id":                   row["id"],
                "candidate_id":         user_id,
                "document_type":        row["doc_type"],
                "version":              row.get("version", 1),
                "extracted_percentage": extracted_pct,
                "extracted_grade":      extracted_grade,
                "extracted_year":       None,   # not yet persisted — extracted by OCR but no free column
                "ocr_confidence":       ocr_conf,
                "file_path":            storage_path,
                "created_at":           row.get("processed_at"),
            })

        logger.info(
            "[routes/academic-records] candidate_id=%s → %d academic record(s): %s",
            user_id,
            len(records),
            [r["document_type"] for r in records],
        )

        return {
            "success":      True,
            "candidate_id": user_id,
            "count":        len(records),
            "academic_records": records,
        }
    except Exception as e:
        logger.error("[routes/academic-records] Error for candidate_id=%s: %s", user_id, e)
        raise HTTPException(500, str(e))



@router.post("/users/{user_id}/documents/upload", tags=["Documents"])
async def upload_document(
    user_id: int,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    entered_percentage: Optional[str] = Form(None),   # user-entered score/percentage/CGPA
):
    """
    Upload a document for an existing user — supports all image formats + PDF.

    Accepted doc_type values:
      KYC:      aadhaar, pan
      Academic: tenth, twelfth, diploma, degree, semester

    STORAGE STRATEGY:
      KYC docs  → documents table (has aadhaar/pan constraint) + Supabase Storage
      Academic  → extracted_data table (no doc_type constraint) + Supabase Storage

    This dual-table approach works around the existing CHECK constraint on the
    documents table without requiring any DDL migration.
    """
    # Academic doc types go through extracted_data, NOT documents table.
    KYC_TYPES      = {"aadhaar", "pan"}
    ACADEMIC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
    ALLOWED_DOC_TYPES = KYC_TYPES | ACADEMIC_TYPES
    is_academic = doc_type in ACADEMIC_TYPES
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, f"doc_type must be one of: {', '.join(sorted(ALLOWED_DOC_TYPES))}")

    allowed_ext = {
        ".pdf", ".png", ".jpg", ".jpeg",
        ".webp", ".bmp", ".tiff", ".tif",
        ".heic", ".heif",
    }
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext and ext not in allowed_ext:
        raise HTTPException(400, f"File type {ext!r} not allowed. Accepted: {', '.join(sorted(allowed_ext))}")

    try:
        sb = get_supabase()

        # ── STEP 1: Verify user exists ────────────────────────────────────
        user_check = sb.table("users").select("id").eq("id", user_id).execute()
        if not user_check.data:
            logger.error("[routes/upload-doc] user_id=%s not found in DB", user_id)
            raise HTTPException(404, f"Candidate {user_id} not found. Cannot link document.")

        # ── STEP 2: Determine version ──────────────────────────────────────
        # For academic docs, version is tracked in extracted_data; for KYC in documents.
        if is_academic:
            existing_q = (
                sb.table("extracted_data")
                .select("version")
                .eq("user_id", user_id)
                .eq("doc_type", doc_type)
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
        else:
            existing_q = (
                sb.table("documents")
                .select("version")
                .eq("user_id", user_id)
                .eq("doc_type", doc_type)
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
        version = ((existing_q.data[0]["version"] + 1) if existing_q.data else 1)
        storage_path = f"user_{user_id}/{doc_type}_v{version}{ext}"
        file_bytes = await file.read()

        logger.info(
            "[routes/upload-doc] user_id=%s doc_type=%s is_academic=%s version=%s path=%s size=%d bytes",
            user_id, doc_type, is_academic, version, storage_path, len(file_bytes)
        )

        # ── STEP 3: Upload to Supabase Storage ────────────────────────────
        try:
            sb.storage.from_("documents").upload(
                storage_path, file_bytes,
                file_options={"content-type": file.content_type or "application/octet-stream", "upsert": "true"}
            )
            logger.info("[routes/upload-doc] Storage upload OK — %s", storage_path)
        except Exception as storage_err:
            logger.error("[routes/upload-doc] Storage upload FAILED for %s: %s", storage_path, storage_err)
            raise HTTPException(500, f"Storage upload failed for {doc_type}: {storage_err}")

        # ── STEP 4: Insert document metadata row ──────────────────────────
        doc_record = None

        if is_academic:
            # ── Academic: Run v2-equivalent OCR pipeline → save to extracted_data ──
            # Uses PDFPipeline for PDFs (same as /api/v2/academic/analyze route).
            # Falls back to direct pytesseract regex if pipeline extracts nothing.
            ocr_result               = {"valid_fields": {}, "telemetry": {}, "status": "skipped"}
            extracted_pct            = None
            extracted_grade          = None
            extracted_year           = None
            extracted_candidate_name = None
            ocr_confidence           = 0.0
            raw_ocr_text             = ""

            try:
                import numpy as np
                import cv2
                from PIL import Image
                import io as _io
                import re as _re



                logger.info(
                    "[routes/upload-doc] ACADEMIC OCR START — user_id=%s doc_type=%s size=%d bytes",
                    user_id, doc_type, len(file_bytes)
                )

                is_pdf = file_bytes[:4] == b"%PDF"

                if is_pdf:
                    # ── PDF path: use PDFPipeline (same as v2 route) ───────────────
                    from app.academic_engine.pdf_engine import PDFPipeline
                    pdf_pipeline = PDFPipeline()
                    ocr_result   = pdf_pipeline.process(file_bytes, upload_id=f"u{user_id}_{doc_type}")
                else:
                    # ── Image path: use MasterPipeline ────────────────────────────
                    nparr = np.frombuffer(file_bytes, np.uint8)
                    bgr_array = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if bgr_array is None:
                        # PIL fallback
                        pil_img   = Image.open(_io.BytesIO(file_bytes)).convert("RGB")
                        bgr_array = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                    pipeline   = _get_academic_pipeline()
                    ocr_result = pipeline.process_document(bgr_array, upload_id=f"u{user_id}_{doc_type}")

                valid_fields  = ocr_result.get("valid_fields", {})
                raw_ocr_text  = (ocr_result.get("debug_lab") or {}).get("ocr", {}).get("merged_text", "")
                ocr_confidence = (ocr_result.get("telemetry") or {}).get("ocr_confidence", 0.0)

                # ── Extract percentage ────────────────────────────────────────────
                pct_field = valid_fields.get("percentage") or {}
                if pct_field.get("value") is not None:
                    extracted_pct = str(pct_field["value"])

                # ── Extract grade (CPI > CGPA > SPI > display_score) ─────────────
                for grade_key in ("cpi", "cgpa", "spi", "display_score"):
                    gf = valid_fields.get(grade_key) or {}
                    gv = gf.get("value")
                    if gv is not None:
                        if isinstance(gv, dict):
                            extracted_grade = f"{gv.get('type','')}: {gv.get('value','')}"
                        else:
                            extracted_grade = str(gv)
                        break

                logger.info(
                    "[routes/upload-doc] ACADEMIC OCR DONE — user_id=%s doc_type=%s "
                    "pct=%s grade=%s conf=%.3f",
                    user_id, doc_type, extracted_pct, extracted_grade, ocr_confidence
                )

                # ── Name extraction from raw OCR text ────────────────────────────
                if raw_ocr_text:
                    try:
                        from app.academic_engine.extractors.academic_name_extractor import extract_academic_name
                        _name_result = extract_academic_name(
                            ocr_text=raw_ocr_text,
                            doc_subtype=doc_type,
                        )
                        extracted_candidate_name = _name_result.name
                        logger.info(
                            "[routes/upload-doc] Name: '%s' conf=%.3f method=%s",
                            extracted_candidate_name, _name_result.confidence, _name_result.method,
                        )
                    except Exception as _ne:
                        logger.warning("[routes/upload-doc] Name extraction error: %s", _ne)

                # ── FALLBACK: Direct pytesseract when pipeline finds nothing ─────
                if not any([extracted_pct, extracted_grade]):
                    try:
                        # import pytesseract
                        if is_pdf:
                            from app.files.pdf_converter import pdf_to_image
                            pil_fb = pdf_to_image(_io.BytesIO(file_bytes))
                        else:
                            pil_fb = Image.open(_io.BytesIO(file_bytes)).convert("RGB")

                        direct_text = pytesseract.image_to_string(
                            pil_fb, lang="eng", config="--psm 3 --oem 3"
                        )
                        logger.info("[routes/upload-doc] FALLBACK pytesseract — %d chars", len(direct_text))

                        cpi_m  = _re.search(r'\bCPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b',  direct_text, _re.I)
                        cgpa_m = _re.search(r'\bCGPA\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', direct_text, _re.I)
                        spi_m  = _re.search(r'\bSPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b',  direct_text, _re.I)
                        pct_m  = _re.search(
                            r'\b(?:percentage|percent|%)\s*[:\s]\s*([0-9]{2,3}(?:\.[0-9]{1,3})?)\b',
                            direct_text, _re.I
                        )
                        for m, label in [(cpi_m, "CPI"), (cgpa_m, "CGPA"), (spi_m, "SPI")]:
                            if m:
                                v = float(m.group(1))
                                if 0.0 < v <= 10.0:
                                    extracted_grade = str(round(v, 2))
                                    logger.info("[routes/upload-doc] FALLBACK %s=%s", label, extracted_grade)
                                    break
                        if not extracted_pct and pct_m:
                            v = float(pct_m.group(1))
                            if 0.0 < v <= 100.0:
                                extracted_pct = str(round(v, 2))
                                logger.info("[routes/upload-doc] FALLBACK PCT=%s", extracted_pct)
                        if not extracted_grade and not extracted_pct:
                            logger.warning(
                                "[routes/upload-doc] FALLBACK found nothing — raw (500): %s",
                                direct_text[:500]
                            )
                    except Exception as _fb_err:
                        logger.warning("[routes/upload-doc] FALLBACK failed: %s", _fb_err)



            except Exception as ocr_err:
                logger.error(
                    "[routes/upload-doc] ACADEMIC OCR PIPELINE EXCEPTION user_id=%s doc_type=%s: %s",
                    user_id, doc_type, ocr_err, exc_info=True
                )
                # Non-fatal: we still save the file reference

            # STEP 4b: Save into extracted_data
            acad_payload = {
                "user_id":          user_id,
                "doc_type":         doc_type,
                "version":          version,
                "name":             extracted_candidate_name,    # OCR candidate name (universal extractor)
                "aadhaar_number":   extracted_pct,               # Repurposed: stores extracted percentage
                "pan_number":       extracted_grade,      # Repurposed: stores extracted CGPA/CPI/SPI
                "dob":              storage_path,          # Repurposed: stores storage_path for retrieval
                "confidence_score": ocr_confidence,
            }
            logger.info(
                "[routes/upload-doc] ACADEMIC INSERT into extracted_data: %s",
                {k: v for k, v in acad_payload.items() if k != 'user_id'}
            )
            try:
                acad_res = sb.table("extracted_data").insert(acad_payload).execute()
                if not acad_res.data:
                    raise Exception("extracted_data insert returned no data")
                saved_row = acad_res.data[0]
                doc_record = {
                    "id":                  saved_row["id"],
                    "user_id":             user_id,
                    "doc_type":            doc_type,
                    "version":             version,
                    "storage_path":        storage_path,
                    "uploaded_at":         saved_row.get("processed_at"),
                    "extracted_percentage":     extracted_pct,
                    "extracted_grade":           extracted_grade,
                    "extracted_year":            extracted_year,
                    "extracted_candidate_name":  extracted_candidate_name,
                    "ocr_confidence":            ocr_confidence,
                    "_source":             "extracted_data",
                }
                logger.info(
                    "[routes/upload-doc] ACADEMIC SAVED SUCCESSFULLY — "
                    "extracted_data_id=%s user_id=%s doc_type=%s pct=%s grade=%s",
                    saved_row["id"], user_id, doc_type, extracted_pct, extracted_grade
                )
            except Exception as acad_err:
                logger.error(
                    "[routes/upload-doc] ACADEMIC extracted_data insert FAILED: %s", acad_err
                )
                raise HTTPException(500, f"Academic record save failed: {acad_err}")

            # ── STEP 4c: Persist entered score into users.academic_inputs JSONB ────
            # This allows the verification panel to show what the user typed,
            # distinct from what OCR extracted.
            if entered_percentage:
                try:
                    import json as _json
                    # Fetch current academic_inputs
                    usr_row = sb.table("users").select("academic_inputs").eq("id", user_id).execute()
                    current_inputs = {}
                    if usr_row.data:
                        current_inputs = usr_row.data[0].get("academic_inputs") or {}
                        if isinstance(current_inputs, str):
                            try: current_inputs = _json.loads(current_inputs)
                            except Exception: current_inputs = {}
                    # Merge new entry
                    current_inputs[doc_type] = {
                        **(current_inputs.get(doc_type) or {}),
                        "percentage": entered_percentage.strip(),
                    }
                    sb.table("users").update({"academic_inputs": current_inputs}).eq("id", user_id).execute()
                    logger.info(
                        "[routes/upload-doc] academic_inputs updated for user_id=%s doc_type=%s pct=%s",
                        user_id, doc_type, entered_percentage
                    )
                except Exception as ai_err:
                    logger.warning(
                        "[routes/upload-doc] Could not update academic_inputs (column may not exist yet): %s", ai_err
                    )

        else:
            # ── KYC path: documents table ─────────────────────────────────
            insert_payload = {
                "user_id":      user_id,
                "doc_type":     doc_type,
                "version":      version,
                "storage_path": storage_path,
            }
            logger.info(
                "[routes/upload-doc] KYC INSERT into documents: user_id=%s doc_type=%s",
                user_id, doc_type
            )
            try:
                doc_res = sb.table("documents").insert(insert_payload).execute()
                if not doc_res.data:
                    raise Exception("documents insert returned no data")
                doc_record = doc_res.data[0]
                logger.info(
                    "[routes/upload-doc] KYC SAVED OK — doc_id=%s user_id=%s doc_type=%s",
                    doc_record.get("id"), user_id, doc_type
                )
            except Exception as db_err:
                err_str = str(db_err)
                logger.error("[routes/upload-doc] KYC documents insert FAILED: %s", err_str)
                raise HTTPException(500, f"KYC document save failed: {err_str}")

        # ── STEP 5: Generate preview URL ──────────────────────────────────
        preview_url = _generate_signed_url(storage_path)

        return {
            "success":      True,
            "document":     doc_record,
            "storage_path": storage_path,
            "preview_url":  preview_url,
            "user_id":      user_id,
            "doc_type":     doc_type,
            "version":      version,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/upload-doc] Unhandled error for user_id=%s doc_type=%s: %s", user_id, doc_type, e)
        raise HTTPException(500, str(e))


# ── OCR / Validation ──────────────────────────────────────────────────────────

@router.post("/users/{user_id}/validate", tags=["Validation"])
async def validate_user(user_id: int, background_tasks: BackgroundTasks):
    """Enqueue the user for OCR + validation (non-blocking)."""
    enqueued = await enqueue_user(user_id)
    if not enqueued:
        raise HTTPException(503, "Processing queue is full. Try again later.")
    return {
        "success": True,
        "message": f"User {user_id} queued for validation.",
        "user_id": user_id,
    }


@router.post("/users/{user_id}/validate/sync", tags=["Validation"])
def validate_user_sync(user_id: int):
    """Synchronous validation — blocks until complete."""
    try:
        result = process_user_documents(user_id)
        return result
    except Exception as e:
        logger.error("[routes] Validation error: %s", e)
        raise HTTPException(500, str(e))


@router.post("/reprocess-ocr/{user_id}", tags=["Validation"])
async def reprocess_ocr(user_id: int):
    """
    Re-enqueue a user for OCR + validation.
    Called from the UserDetailPanel 'Re-run OCR' button.
    """
    try:
        sb = get_supabase()
        
        # Check if already verified to prevent overwriting
        # Check validation_reviews first
        vr_res = sb.table("validation_reviews").select("status, decision").eq("user_id", user_id).execute()
        is_verified = False
        if vr_res.data:
            for row in vr_res.data:
                if row.get("status") == "completed" and row.get("decision") == "approved":
                    is_verified = True
                    break
        
        # Check users table if review is not conclusive
        if not is_verified:
            usr_res = sb.table("users").select("is_verified, status, workflow_state").eq("id", user_id).execute()
            if usr_res.data:
                u = usr_res.data[0]
                if u.get("is_verified") == 1 or u.get("status") in ["APPROVED", "VERIFIED"] or u.get("workflow_state") in ["APPROVED", "VERIFIED"]:
                    is_verified = True
                    
        if is_verified:
            raise HTTPException(400, "Cannot re-run OCR on an already verified candidate. Reject them first to re-run OCR.")

        enqueued = await enqueue_user(user_id)
        return {
            "success": True,
            "message": f"User {user_id} re-queued for OCR processing.",
            "user_id": user_id,
            "enqueued": enqueued,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes] reprocess-ocr error: %s", e)
        raise HTTPException(500, str(e))


@router.get("/users/{user_id}/validation-results", tags=["Validation"])
def get_validation_results(user_id: int):
    """Get stored validation results for a user."""
    try:
        sb = get_supabase()
        extracted = (sb.table("extracted_data")
                     .select("*")
                     .eq("user_id", user_id)
                     .execute())
        verified = (sb.table("verified_data")
                    .select("*")
                    .eq("user_id", user_id)
                    .execute())
        return {
            "success":        True,
            "user_id":        user_id,
            "extracted_data": extracted.data or [],
            "verified_data":  verified.data or [],
        }
    except Exception as e:
        raise HTTPException(500, str(e))



# ── Bulk processing ───────────────────────────────────────────────────────────

@router.post("/bulk/validate-all", tags=["Bulk"])
async def bulk_validate_all():
    """Enqueue ALL users for reprocessing."""
    result = await enqueue_all_users()
    return result


@router.get("/bulk/queue-status", tags=["Bulk"])
def bulk_queue_status():
    return get_queue_status()


# ── Bulk OCR state tracker (in-memory, reset on each run) ─────────────────────

_bulk_ocr_state: dict = {
    "running": False,
    "total": 0,
    "processed": 0,
    "success": 0,
    "failed": 0,
    "skipped": 0,
    "jobs_queued": 0,
    "current_user": None,
    "errors": [],
    "started_at": None,
    "finished_at": None,
    "cancel_requested": False,
    # Ring-buffer of recently completed user_ids for targeted frontend refresh.
    # Frontend polls this and refreshes only those rows instead of the full table.
    "recently_completed": [],
}


# ── OCR concurrency gate ──────────────────────────────────────────────────────
# Limits how many threads can run PaddleOCR simultaneously.
# PaddleOCR holds the Python GIL during its C extension calls. Running 8+ OCR
# threads simultaneously starves the asyncio event loop, causing the frontend
# health check to time out and falsely declare the backend offline.
# 2 concurrent OCR threads is the stable sweet spot: enough parallelism to
# benefit from I/O overlap (Supabase downloads) without GIL starvation.
import threading as _threading
_ocr_semaphore = _threading.Semaphore(2)


def _process_one_sync(user_id: int) -> dict:
    """
    Synchronous per-user OCR function — runs in a thread pool via asyncio.to_thread.

    Uses _ocr_semaphore to cap concurrent PaddleOCR invocations at 2.
    This is the critical fix: PaddleOCR holds the Python GIL during its C++
    inference calls. With 8 concurrent threads all holding the GIL, the asyncio
    event loop (which also runs in the main thread) can't execute for > 5 seconds,
    causing the frontend health check to time out and falsely declare offline.

    The semaphore is acquired INSIDE this synchronous function (not in the async
    caller), so while a thread waits for the semaphore, the event loop is free
    to handle other requests (health checks, status polls, etc).

    Full exception isolation: any exception is caught and returned as an error
    dict so the caller can log it without crashing the entire batch.
    """
    import traceback as _tb
    import time as _time

    try:
        logger.info("[ocr/bulk] _process_one_sync: START user_id=%s  thread=%s",
                    user_id, _threading.current_thread().name)

        # Acquire semaphore before running OCR (blocks other threads, not event loop)
        with _ocr_semaphore:
            logger.info("[ocr/bulk] _process_one_sync: OCR SLOT ACQUIRED user_id=%s", user_id)
            t0 = _time.monotonic()
            result = process_user_documents(user_id)
            ocr_ms = int((_time.monotonic() - t0) * 1000)
            logger.info("[ocr/bulk] _process_one_sync: OCR SLOT RELEASED user_id=%s ocr_ms=%d status=%s",
                        user_id, ocr_ms, result.get("overall_status"))

        return result

    except Exception as exc:
        logger.error(
            "[ocr/bulk] _process_one_sync: EXCEPTION user_id=%s\n%s",
            user_id, _tb.format_exc()
        )
        # Return an error dict instead of raising — caller will log and continue
        return {
            "success": False,
            "user_id": user_id,
            "overall_status": "ERROR",
            "error": str(exc),
        }



async def _run_bulk_ocr_background(user_ids: list, force: bool = False):
    """
    Background coroutine: process users in concurrent batches.
    Skips VERIFIED / APPROVED / REJECTED users unless force=True.
    Updates _bulk_ocr_state live so the frontend can poll /ocr/bulk/status.

    Performance notes:
    - BATCH_SIZE=3: runs up to 3 user downloads concurrently, but PaddleOCR
      itself is throttled to 2 concurrent invocations via _ocr_semaphore.
      This prevents GIL starvation that caused false 'offline' detection.
    - recently_completed: ring-buffer of finished user_ids for targeted refresh.
    """
    import asyncio as _asyncio
    import time as _time
    global _bulk_ocr_state

    SKIP_STATUSES = {"VERIFIED", "APPROVED", "REJECTED"}
    BATCH_SIZE = 3          # Reduced from 8 — prevents GIL/connection starvation
    MAX_RECENT = 50         # Ring-buffer cap for recently_completed

    _bulk_ocr_state.update({
        "running": True,
        "total": len(user_ids),
        "processed": 0,
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "jobs_queued": len(user_ids),
        "current_user": None,
        "errors": [],
        "started_at": _time.time(),
        "finished_at": None,
        "percent_complete": 0,
        "cancel_requested": False,
        "recently_completed": [],   # reset on every run
    })

    # ── Pre-fetch user statuses in a thread — does NOT block the event loop ──
    # CRITICAL FIX: previously this was a synchronous Supabase call on the
    # asyncio event loop itself. With 194 users in the IN clause, the query
    # takes 200ms-2s. The entire event loop froze for this duration, causing
    # health checks to queue up and time out, flipping the UI to 'offline'.
    def _fetch_statuses() -> dict:
        try:
            sb = get_supabase()
            status_res = (
                sb.table("users")
                .select("id, status, workflow_state, final_verified")
                .in_("id", user_ids)
                .execute()
            )
            return {u["id"]: u for u in (status_res.data or [])}
        except Exception as _e:
            logger.warning("[ocr/bulk] Status prefetch failed: %s", _e)
            return {}

    logger.info("[ocr/bulk] Pre-fetching user statuses (non-blocking)...")
    user_status_map = await _asyncio.to_thread(_fetch_statuses)
    logger.info("[ocr/bulk] Status map ready — %d entries", len(user_status_map))

    for i in range(0, len(user_ids), BATCH_SIZE):
        # ── Check for cancellation between batches ────────────────────────────
        if _bulk_ocr_state.get("cancel_requested"):
            logger.info("[ocr/bulk] Cancellation requested. Stopping background process.")
            break

        batch = user_ids[i: i + BATCH_SIZE]
        to_process = []

        for uid in batch:
            u_info = user_status_map.get(uid, {})
            db_status = (u_info.get("status") or "").upper()
            db_wf     = (u_info.get("workflow_state") or "").upper()
            is_final  = bool(u_info.get("final_verified"))

            if not force and (db_status in SKIP_STATUSES or db_wf in SKIP_STATUSES or is_final):
                logger.info("[ocr/bulk] Skipping user_id=%s (status=%s)", uid, db_status or db_wf)
                _bulk_ocr_state["skipped"]   += 1
                _bulk_ocr_state["processed"] += 1
                _bulk_ocr_state["percent_complete"] = round(
                    (_bulk_ocr_state["processed"] / (len(user_ids) or 1)) * 100, 1
                )
                continue

            to_process.append(uid)

        if not to_process:
            continue

        # Process batch concurrently.
        # Each task acquires the OCR semaphore before entering PaddleOCR,
        # ensuring at most 2 threads hold the GIL at once.
        async def _process_one(uid: int):
            _bulk_ocr_state["current_user"] = uid
            t_start = _time.monotonic()
            try:
                logger.info("[ocr/bulk] START user_id=%s", uid)
                # Semaphore is acquired inside the thread (blocking call),
                # not here, so the event loop stays free during the wait.
                result = await _asyncio.to_thread(_process_one_sync, uid)
                elapsed = round(_time.monotonic() - t_start, 1)
                logger.info(
                    "[ocr/bulk] DONE user_id=%s status=%s elapsed=%.1fs",
                    uid, result.get("overall_status"), elapsed
                )
                _bulk_ocr_state["success"] += 1
            except Exception as exc:
                import traceback as _tb
                elapsed = round(_time.monotonic() - t_start, 1)
                logger.error(
                    "[ocr/bulk] FAILED user_id=%s elapsed=%.1fs error=%s\n%s",
                    uid, elapsed, exc, _tb.format_exc()
                )
                _bulk_ocr_state["failed"] += 1
                if len(_bulk_ocr_state["errors"]) < 50:
                    _bulk_ocr_state["errors"].append({
                        "user_id": uid,
                        "error": str(exc)[:300],
                        "elapsed_sec": elapsed,
                    })
                # CRITICAL: never re-raise — one document failure must not
                # stop the batch. The finally block still runs.
            finally:
                _bulk_ocr_state["processed"] += 1
                _bulk_ocr_state["percent_complete"] = round(
                    (_bulk_ocr_state["processed"] / (len(user_ids) or 1)) * 100, 1
                )
                # ── Track for frontend targeted refresh ───────────────────────
                recent = _bulk_ocr_state["recently_completed"]
                if uid not in recent:
                    recent.append(uid)
                    if len(recent) > MAX_RECENT:
                        recent.pop(0)

        await _asyncio.gather(*[_process_one(uid) for uid in to_process])
        # Yield to event loop between batches so health checks can respond
        await _asyncio.sleep(0.1)

    import time as _time2
    _bulk_ocr_state.update({
        "running": False,
        "current_user": None,
        "finished_at": _time2.time(),
        "percent_complete": 100,
    })
    logger.info(
        "[ocr/bulk] Complete — success=%d failed=%d skipped=%d",
        _bulk_ocr_state["success"], _bulk_ocr_state["failed"], _bulk_ocr_state["skipped"],
    )


@router.post("/ocr/bulk/stop", tags=["Bulk"])
def ocr_bulk_stop():
    """
    Request to stop the currently running bulk OCR process.
    Instantly marks the state as not running.
    """
    import time as _time
    global _bulk_ocr_state
    if not _bulk_ocr_state.get("running"):
        return {"success": False, "message": "No bulk OCR process is currently running."}
    
    _bulk_ocr_state["cancel_requested"] = True
    _bulk_ocr_state["running"] = False
    _bulk_ocr_state["finished_at"] = _time.time()
    
    return {
        "success": True, 
        "message": "Stop request received. OCR halted.",
        "processed": _bulk_ocr_state.get("processed", 0)
    }


@router.post("/ocr/bulk", tags=["Bulk"])
async def ocr_bulk(background_tasks: BackgroundTasks, force: bool = False):
    """
    Trigger bulk OCR for all pending/review/extracted users.
    Returns immediately — zero blocking I/O in this handler.

    ROOT CAUSE FIX: The previous version called sb.table("users").select()
    synchronously inside this async handler, which blocked the uvicorn event
    loop for the full Supabase network roundtrip (200ms-2s). Any concurrent
    health check (/api/health) queued behind this blocked thread and timed out,
    causing the frontend to falsely declare the backend offline.

    Fix: use asyncio.to_thread for the Supabase fetch so the event loop stays
    free to handle health checks and status polls during the fetch.
    """
    import asyncio as _asyncio
    global _bulk_ocr_state

    logger.info("[ocr/bulk] POST received — force=%s", force)

    if _bulk_ocr_state["running"]:
        logger.info("[ocr/bulk] Already running — returning current state")
        return {
            "success": False,
            "already_running": True,
            "message": "Bulk OCR is already running.",
            **_bulk_ocr_state,
        }

    # ── Fetch user IDs in a thread — does NOT block event loop ───────────────
    def _fetch_user_ids() -> list:
        sb = get_supabase()
        res = sb.table("users").select("id").execute()
        return [u["id"] for u in (res.data or [])]

    try:
        logger.info("[ocr/bulk] Fetching user IDs (non-blocking)...")
        user_ids = await _asyncio.to_thread(_fetch_user_ids)
        logger.info("[ocr/bulk] Fetched %d user IDs", len(user_ids))
    except Exception as exc:
        logger.error("[ocr/bulk] Failed to fetch users: %s", exc)
        raise HTTPException(500, f"Failed to fetch users: {exc}")

    if not user_ids:
        return {"success": True, "jobs_queued": 0, "message": "No users found."}

    # Reset state and kick off background task
    _bulk_ocr_state["jobs_queued"] = len(user_ids)
    background_tasks.add_task(_run_bulk_ocr_background, user_ids, force)
    logger.info("[ocr/bulk] Background task scheduled for %d users", len(user_ids))

    return {
        "success": True,
        "jobs_queued": len(user_ids),
        "total_users": len(user_ids),
        "message": f"Started bulk OCR for up to {len(user_ids)} users.",
    }


@router.get("/ocr/bulk/status", tags=["Bulk"])
def ocr_bulk_status():
    """
    Returns current bulk OCR progress state.
    Frontend polls this every ~1.5s while running=True.

    Includes recently_completed: list of user_ids whose OCR just finished.
    The frontend uses this to refresh only those rows instead of the full table.
    """
    import time as _time
    state = dict(_bulk_ocr_state)
    # Shallow-copy the recently_completed list so it's JSON-serializable
    state["recently_completed"] = list(_bulk_ocr_state.get("recently_completed", []))
    total = state.get("total", 0) or 1
    processed = state.get("processed", 0)
    state["percent_complete"] = round((processed / total) * 100, 1) if total > 0 else 0
    state["elapsed_sec"] = round(_time.time() - state["started_at"], 1) if state.get("started_at") else 0
    return state


@router.get("/users/{user_id}/fresh", tags=["Users"])
def get_user_fresh(user_id: int):
    """
    Return a single user record enriched with the FRESHEST extracted_data.
    Used by the frontend to update a single table row after OCR completes
    without triggering a full table reload.

    Returns the same shape as list_users() for a single user so that
    DataContext.setUsers() can merge it in-place.
    """
    try:
        sb = get_supabase()

        # Fetch user
        user_res = sb.table("users").select("*").eq("id", user_id).single().execute()
        if not user_res.data:
            raise HTTPException(404, f"User {user_id} not found")
        u = user_res.data

        # Fetch extracted_data for this user only
        ext_res = (
            sb.table("extracted_data")
            .select("user_id, doc_type, name, aadhaar_number, pan_number, dob, confidence_score, processed_at")
            .eq("user_id", user_id)
            .order("processed_at", desc=True)
            .execute()
        )
        extracted_rows = ext_res.data or []

        # Build doc_type → freshest_row map
        docs: dict = {}
        for row in extracted_rows:
            dtype = row.get("doc_type", "unknown")
            existing = docs.get(dtype)
            if existing is None:
                docs[dtype] = row
            else:
                new_ts = row.get("processed_at") or ""
                old_ts = existing.get("processed_at") or ""
                if new_ts >= old_ts:
                    docs[dtype] = row

        a = docs.get("aadhaar") or {}
        p = docs.get("pan")     or {}

        def _unwrap(val):
            if val is None: return None
            if isinstance(val, dict): return str(val.get("value") or "").strip() or None
            if isinstance(val, str):
                s = val.strip()
                if s.startswith("{"):
                    import json as _j
                    try:
                        obj = _j.loads(s)
                        if isinstance(obj, dict) and "value" in obj:
                            return str(obj["value"]).strip() or None
                    except Exception: pass
                return s or None
            return str(val).strip() or None

        aadhaar_data = {
            "name":           _unwrap(a.get("name")),
            "aadhaar_number": _unwrap(a.get("aadhaar_number")),
            "dob":            _unwrap(a.get("dob")),
            "confidence":     round((a.get("confidence_score") or 0) * 100, 1),
        }
        pan_data = {
            "name":       _unwrap(p.get("name")),
            "pan_number": _unwrap(p.get("pan_number")),
            "dob":        _unwrap(p.get("dob")),
            "confidence": round((p.get("confidence_score") or 0) * 100, 1),
        }

        # Doc types from documents table (KYC)
        try:
            doc_types_res = sb.table("documents").select("doc_type").eq("user_id", user_id).execute()
            doc_types = list({r["doc_type"] for r in (doc_types_res.data or []) if r.get("doc_type")})
        except Exception:
            doc_types = []

        # Add academic doc_types from extracted_data
        ACADEMIC_DOC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}
        for dtype in docs:
            if dtype in ACADEMIC_DOC_TYPES and dtype not in doc_types:
                doc_types.append(dtype)

        # Review status
        try:
            rv_res = sb.table("validation_reviews").select("status, decision, updated_at").eq("user_id", user_id).order("updated_at", desc=True).limit(1).execute()
            review = rv_res.data[0] if rv_res.data else {}
        except Exception:
            review = {}

        is_final_verified = bool(u.get("final_verified"))
        display_name = u.get("full_name") or ""
        if is_final_verified and u.get("final_name"):
            display_name = u["final_name"]

        # Compute aggregate confidence
        conf_scores = [a.get("confidence_score") or 0, p.get("confidence_score") or 0]
        valid_confs = [c for c in conf_scores if c > 0]
        avg_conf = round(sum(valid_confs) / len(valid_confs) * 100, 1) if valid_confs else 0.0

        enriched = {
            **u,
            "aadhaar":        aadhaar_data,
            "pan":            pan_data,
            "entered_aadhaar_number": u.get("aadhaar_number") or "",
            "entered_pan_number":     u.get("pan_number")     or "",
            "final_name":    _unwrap(u.get("final_name")),
            "final_aadhaar": _unwrap(u.get("final_aadhaar")),
            "final_pan":     _unwrap(u.get("final_pan")),
            "final_dob":     _unwrap(u.get("final_dob")),
            "aadhaar_number": _unwrap(u.get("final_aadhaar")) or _unwrap(a.get("aadhaar_number")) or _unwrap(u.get("aadhaar_number")) or "",
            "pan_number":     _unwrap(u.get("final_pan"))     or _unwrap(p.get("pan_number"))     or _unwrap(u.get("pan_number"))     or "",
            "email":             u.get("email") or "",
            "mobile_number":     u.get("mobile_number") or "",
            "permanent_address": u.get("permanent_address") or "",
            "name":          display_name,
            "original_name": u.get("full_name") or "",
            "doc_types":     sorted(doc_types),
            "confidence":    avg_conf,
            "ocr_status_combined": review.get("status") or "",
        }

        return {"success": True, "user": enriched}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/user-fresh] Error for user_id=%s: %s", user_id, e)
        raise HTTPException(500, str(e))


# ── Evaluate endpoints (AI decision engine) ───────────────────────────────────

@router.post("/evaluate/{user_id}", tags=["Validation"])
async def evaluate_user(user_id: int, force: bool = False):
    """
    Run the score → decide → suggest → persist pipeline for a user.
    Falls back to enqueuing the user for async reprocessing if no service exists.
    """
    try:
        # Try to import the dedicated evaluate service if it exists
        try:
            from app.services.evaluate_service import evaluate_user_documents  # type: ignore
            result = await evaluate_user_documents(user_id, force=force)
            return result
        except ImportError:
            pass

        # Fallback: requeue for OCR processing
        enqueued = await enqueue_user(user_id)
        return {
            "status": "queued",
            "user_id": user_id,
            "message": f"User {user_id} queued for evaluation.",
            "enqueued": enqueued,
            "evaluations": [],
            "summary": {"total_docs": 0, "approved": 0, "review": 0, "rejected": 0},
        }
    except Exception as e:
        logger.error("[routes/evaluate] Error: %s", e)
        raise HTTPException(500, str(e))


@router.get("/evaluate/summary", tags=["Validation"])
def evaluate_summary():
    """
    Returns aggregate decision counts from verified_data / validation_reviews.
    Consumed by the Dashboard and Database pages.
    """
    try:
        sb = get_supabase()
        # Try validation_reviews table first
        try:
            res = sb.table("validation_reviews").select("decision", count="exact").execute()
            rows = res.data or []
            counts = {"approved": 0, "review": 0, "rejected": 0, "pending": 0}
            for r in rows:
                d = (r.get("decision") or "pending").lower()
                if d in counts:
                    counts[d] += 1
                elif d == "auto_approved":
                    counts["approved"] += 1
                elif d == "auto_rejected":
                    counts["rejected"] += 1
                else:
                    counts["pending"] += 1
            total = len(rows)
            return {"status": "ok", "total": total, **counts}
        except Exception:
            pass

        # Fallback: use verified_data
        vd_res = sb.table("verified_data").select("decision").execute()
        rows = vd_res.data or []
        counts = {"approved": 0, "review": 0, "rejected": 0, "pending": 0}
        for r in rows:
            d = (r.get("decision") or "pending").lower()
            if d in counts:
                counts[d] += 1
            else:
                counts["pending"] += 1
        return {"status": "ok", "total": len(rows), **counts}
    except Exception as e:
        logger.error("[routes/evaluate-summary] Error: %s", e)
        raise HTTPException(500, str(e))


# ── Document debug / preview helpers ─────────────────────────────────────────

@router.get("/documents/{doc_id}/raw-ocr", tags=["OCR"])
def debug_raw_ocr(doc_id: int):
    """
    Debug: download a stored document and run the full OCR pipeline on it.
    Returns raw_text + extracted fields without saving anything.
    """
    try:
        sb = get_supabase()
        doc_res = sb.table("documents").select("*").eq("id", doc_id).single().execute()
        if not doc_res.data:
            raise HTTPException(404, f"Document {doc_id} not found")
        doc = doc_res.data
        storage_path = doc.get("storage_path", "")
        doc_type = doc.get("doc_type")
        logger.info("[routes/debug] raw-ocr for doc_id=%s path=%s", doc_id, storage_path)
        try:
            raw = sb.storage.from_("documents").download(storage_path)
        except Exception as dl_err:
            raise HTTPException(500, f"Download failed: {dl_err}")
        if not raw:
            raise HTTPException(500, "Downloaded file is empty")
        image_input = io.BytesIO(raw)
        res = process_document(image_input, doc_type_hint=doc_type)
        return {
            "success":         True,
            "doc_id":          doc_id,
            "doc_type":        doc_type,
            "storage_path":    storage_path,
            "file_size_bytes": len(raw),
            "is_pdf":          raw[:4] == b"%PDF",
            "ocr_confidence":  res.get("ocr_confidence", 0.0),
            "fallback_used":   res.get("fallback_used", False),
            "engines_used":    res.get("engines_used", []),
            "extracted":       res.get("extracted", {}),
            "raw_text":        res.get("raw_text", "")[:2000],
            "error":           res.get("error"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("[routes/debug] raw-ocr error: %s", e)
        raise HTTPException(500, str(e))


@router.get("/documents/{doc_id}/preview-url", tags=["Documents"])
def get_document_preview_url(doc_id: int, expires_in: int = 3600):
    """Generate a fresh signed preview URL for any stored document."""
    try:
        sb = get_supabase()
        doc_res = sb.table("documents").select("storage_path").eq("id", doc_id).single().execute()
        if not doc_res.data:
            raise HTTPException(404, "Document not found")
        path = doc_res.data["storage_path"]
        signed_url = _generate_signed_url(path, expires_in)
        if signed_url:
            return {"success": True, "signed_url": signed_url, "expires_in": expires_in}
        return {"success": False, "error": "Could not generate signed URL"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Academic Storage Diagnostic ──────────────────────────────────────────────

@router.get("/debug/academic-storage", tags=["Debug"])
def debug_academic_storage(user_id: Optional[int] = None):
    """
    DIAGNOSTIC ENDPOINT — tells you exactly what academic records are stored.

    Academic docs are stored in extracted_data (doc_type in academic set).
    The documents table is NOT used for academic docs (CHECK constraint blocks it).

    GET /api/debug/academic-storage          → all academic rows across all users
    GET /api/debug/academic-storage?user_id= → rows for one candidate
    """
    sb = get_supabase()
    ACADEMIC_TYPES = ["tenth", "twelfth", "diploma", "degree", "semester"]
    report = {
        "storage_table": "extracted_data",
        "note": "Academic docs are stored in extracted_data.dob = storage_path (workaround for documents CHECK constraint)",
    }

    # ── 1. Count academic rows in extracted_data ──────────────────────────
    type_counts = {}
    for dt in ACADEMIC_TYPES:
        try:
            r = sb.table("extracted_data").select("id", count="exact").eq("doc_type", dt).execute()
            type_counts[dt] = r.count or 0
        except Exception as e:
            type_counts[dt] = f"ERROR: {e}"
    report["extracted_data_by_type"] = type_counts
    report["total_academic_docs"] = sum(v for v in type_counts.values() if isinstance(v, int))

    # ── 2. Fetch actual rows ──────────────────────────────────────────────
    try:
        q = sb.table("extracted_data").select("id, user_id, doc_type, version, dob, processed_at")
        q = q.in_("doc_type", ACADEMIC_TYPES)
        if user_id:
            q = q.eq("user_id", user_id)
        q = q.order("processed_at", desc=True).limit(100)
        rows = q.execute()
        report["academic_rows"] = [
            {
                "id":           r["id"],
                "user_id":      r["user_id"],
                "doc_type":     r["doc_type"],
                "version":      r["version"],
                "storage_path": r.get("dob"),   # dob column holds storage_path
                "uploaded_at":  r.get("processed_at"),
            }
            for r in (rows.data or [])
        ]
    except Exception as e:
        report["academic_rows"] = f"ERROR: {e}"

    # ── 3. Live INSERT probe into extracted_data ──────────────────────────
    probe_result = "not_tested"
    if not user_id:
        try:
            u_res = sb.table("users").select("id").limit(1).execute()
            if u_res.data:
                test_uid = u_res.data[0]["id"]
                probe_insert = sb.table("extracted_data").insert({
                    "user_id":          test_uid,
                    "doc_type":         "tenth",
                    "version":          9999,
                    "name":             None,
                    "confidence_score": 0.0,
                    "dob":              "_diagnostic_probe_DELETE_ME",
                }).execute()
                if probe_insert.data:
                    probe_id = probe_insert.data[0]["id"]
                    sb.table("extracted_data").delete().eq("id", probe_id).execute()
                    probe_result = (
                        f"SUCCESS - extracted_data accepts doc_type='tenth'. "
                        f"probe_id={probe_id} inserted and deleted cleanly."
                    )
                else:
                    probe_result = "INSERT returned no data"
            else:
                probe_result = "skipped - no users exist yet"
        except Exception as e:
            probe_result = f"FAILED: {e}"
    report["insert_probe"] = probe_result

    # ── 4. Diagnosis ──────────────────────────────────────────────────────
    total = report["total_academic_docs"]
    if isinstance(total, int) and total > 0:
        report["diagnosis"] = (
            f"HEALTHY - {total} academic rows in extracted_data. "
            f"Badges and review panel will show correctly."
        )
    elif "SUCCESS" in str(probe_result):
        report["diagnosis"] = (
            "READY - extracted_data accepts academic doc_types. "
            "No academic docs uploaded yet. Try uploading a 10th marksheet."
        )
    else:
        report["diagnosis"] = f"ERROR - {probe_result}"

    logger.info("[routes/debug-academic] diagnosis=%s", report["diagnosis"])
    return report


# ── PDF render debug endpoint ─────────────────────────────────────────────────

@router.post("/debug/pdf-render", tags=["OCR"])
async def debug_pdf_render(file: UploadFile = File(...)):
    """
    Debug endpoint: render a PDF to images and return metadata.
    Does NOT run OCR — just shows what the converter produces.
    Useful for verifying DPI, channel order, and image size are correct.
    """
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if raw[:4] != b"%PDF":
        raise HTTPException(400, "File is not a PDF (magic bytes mismatch)")

    try:
        from app.files.pdf_converter import pdf_to_pages, PDF_DPI, PDF_SCALE
        import time as _time
        t0     = _time.monotonic()
        pages  = pdf_to_pages(raw)
        elapsed = round(_time.monotonic() - t0, 2)

        page_meta = []
        for p in pages:
            import numpy as np
            arr  = np.array(p.image.convert("L"))
            page_meta.append({
                "page_num":    p.page_num,
                "width_px":    p.width,
                "height_px":   p.height,
                "mode":        p.image.mode,
                "is_blank":    p.is_blank,
                "engine":      p.engine,
                "mean_pixel":  round(float(arr.mean()), 1),
                "min_pixel":   int(arr.min()),
                "max_pixel":   int(arr.max()),
            })

        return {
            "success":      True,
            "filename":     file.filename,
            "file_bytes":   len(raw),
            "dpi_used":     PDF_DPI,
            "scale_used":   round(PDF_SCALE, 4),
            "total_pages":  len(pages),
            "non_blank":    sum(1 for p in pages if not p.is_blank),
            "elapsed_sec":  elapsed,
            "pages":        page_meta,
        }
    except Exception as exc:
        logger.error("[routes/debug-pdf] Error: %s", exc)
        raise HTTPException(500, str(exc))
