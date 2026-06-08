"""
app/fraud/fraud_engine.py — Master fraud analysis orchestrator
==============================================================
analyze_document() is the single public entry point.

Full pipeline:
  1. Quality analysis      → quality_score, blur, brightness, flags
  2. Tampering detection   → tamper_score, tamper_flags, ELA, edge anomaly
  3. Metadata analysis     → EXIF, screenshot, software traces
  4. Duplicate detection   → image hash + ID-level cross-user check
  5. Pattern analysis      → behavioural signals for this user
  6. Risk scoring          → master risk_score (0-100), risk_level
  7. DB persistence        → fraud_analysis + risk_scores tables
  8. Review priority       → update review queue priority if linked review
"""

from __future__ import annotations
import io
import json
from typing import Dict, Optional
from datetime import datetime, timezone
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.fraud.quality_analyzer    import analyze_quality
from app.fraud.tamper_detector     import detect_tampering
from app.fraud.metadata_analyzer   import analyze_metadata
from app.fraud.duplicate_detector  import analyze_duplicates
from app.fraud.suspicious_patterns import analyze_patterns
from app.fraud.risk_scorer         import calculate_risk_score, map_risk_to_review_priority


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe(obj) -> Dict:
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_image_bytes(image_input) -> bytes:
    """Extract raw bytes for file size calculation."""
    try:
        if isinstance(image_input, bytes):
            return image_input
        if hasattr(image_input, "read"):
            pos  = image_input.tell()
            data = image_input.read()
            image_input.seek(pos)
            return data
    except Exception:
        pass
    return b""


# ── DB persistence ────────────────────────────────────────────────────────────

def _save_fraud_analysis(user_id: int, document_id: Optional[int],
                          doc_type: str, result: Dict) -> Optional[str]:
    """Insert into fraud_analysis table, return new ID."""
    payload = {
        "user_id":            user_id,
        "document_id":        document_id,
        "doc_type":           doc_type,

        "quality_score":      result.get("quality_score", 0),
        "blur_score":         result.get("blur_score", 0),
        "brightness_score":   result.get("brightness", 0),
        "contrast_score":     result.get("contrast", 0),
        "noise_score":        result.get("noise", 0),
        "quality_flags":      _safe(result.get("quality_flags", [])),

        "tamper_score":       result.get("tamper_score", 0),
        "tamper_flags":       _safe(result.get("tamper_flags", [])),

        "duplicate_detected": result.get("duplicate_detected", False),
        "duplicate_score":    result.get("duplicate_score", 0),
        "duplicate_matches":  _safe(result.get("duplicate_matches", [])),

        "metadata_flags":     _safe(result.get("metadata_flags", [])),
        "is_screenshot":      result.get("is_screenshot", False),
        "has_exif":           result.get("has_exif", False),
        "exif_software":      result.get("exif_software"),

        "risk_score":         result.get("risk_score", 0),
        "risk_level":         result.get("risk_level", "LOW_RISK"),
        "recommendation":     result.get("recommendation", ""),
        "risk_breakdown":     _safe(result.get("component_scores", {})),

        "analyzed_at":        _now(),
        "created_at":         _now(),
    }
    try:
        sb  = get_supabase()
        res = sb.table("fraud_analysis").insert(payload).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.error("[fraud_engine] _save_fraud_analysis error: %s", exc)
        return None


def _save_risk_score(fraud_id: str, user_id: int, document_id: Optional[int],
                     risk_result: Dict) -> None:
    """Append immutable risk_scores record."""
    payload = {
        "fraud_analysis_id": fraud_id,
        "user_id":           user_id,
        "document_id":       document_id,
        "risk_score":        risk_result.get("risk_score", 0),
        "risk_level":        risk_result.get("risk_level", "LOW_RISK"),
        "component_scores":  _safe(risk_result.get("component_scores", {})),
        "created_at":        _now(),
    }
    try:
        sb = get_supabase()
        sb.table("risk_scores").insert(payload).execute()
    except Exception as exc:
        logger.error("[fraud_engine] _save_risk_score error: %s", exc)


def _save_tamper_flags(fraud_id: str, details: list) -> None:
    """Persist per-flag tamper evidence records."""
    if not details:
        return
    sb = get_supabase()
    rows = [{
        "fraud_id":    fraud_id,
        "flag_type":   d.get("flag", "unknown"),
        "severity":    d.get("severity", "low"),
        "description": d.get("description", ""),
        "confidence":  50,
        "created_at":  _now(),
    } for d in details]
    try:
        sb.table("tamper_flags").insert(rows).execute()
    except Exception as exc:
        logger.error("[fraud_engine] _save_tamper_flags error: %s", exc)


def _update_review_priority(user_id: int, risk_level: str) -> None:
    """Update pending review priority based on fraud risk level."""
    priority = map_risk_to_review_priority(risk_level)
    try:
        sb = get_supabase()
        sb.table("validation_reviews").update({"priority": priority}).eq("user_id", user_id).in_("status", ["pending", "in_review"]).execute()
        logger.info("[fraud_engine] Updated review priority to %d for user=%s (risk=%s)", priority, user_id, risk_level)
    except Exception as exc:
        logger.debug("[fraud_engine] _update_review_priority error: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_document(
    image_input,
    user_id:        int,
    doc_type:       str = "unknown",
    document_id:    Optional[int] = None,
    ocr_confidence: float = 1.0,
    extracted:      Optional[Dict] = None,
) -> Dict:
    """
    Master fraud analysis pipeline.

    Args:
        image_input:    file path | PIL.Image | bytes | BytesIO | np.ndarray
        user_id:        user being validated
        doc_type:       'aadhaar' | 'pan' | 'unknown'
        document_id:    DB document ID (optional)
        ocr_confidence: from OCR pipeline (affects risk score)
        extracted:      parsed fields {aadhaar_number, pan_number, ...}

    Returns the required output format:
        {
            "fraud_id":           str (DB record ID),
            "risk_level":         str,
            "risk_score":         int (0-100),
            "quality_score":      int,
            "duplicate_detected": bool,
            "tamper_flags":       [str],
            "metadata_flags":     [str],
            "quality_flags":      [str],
            "recommendation":     str,
            "component_scores":   {...},
            "is_screenshot":      bool,
        }
    """
    logger.info(
        "[fraud_engine] Analyzing user_id=%s doc_type=%s doc_id=%s",
        user_id, doc_type, document_id
    )

    # ── 1. Quality analysis ───────────────────────────────────────────────────
    quality_result = analyze_quality(image_input)

    # ── 2. Tampering detection ────────────────────────────────────────────────
    tamper_result = detect_tampering(image_input)

    # ── 3. Metadata analysis ──────────────────────────────────────────────────
    meta_result = analyze_metadata(image_input)

    # ── 4. Duplicate detection ────────────────────────────────────────────────
    raw_bytes    = _get_image_bytes(image_input)
    file_size_kb = len(raw_bytes) / 1024.0
    aadhaar_num  = (extracted or {}).get("aadhaar_number")
    pan_num      = (extracted or {}).get("pan_number")

    dup_result = analyze_duplicates(
        image_input    = image_input,
        user_id        = user_id,
        doc_type       = doc_type,
        document_id    = document_id,
        aadhaar_number = aadhaar_num,
        pan_number     = pan_num,
        file_size_kb   = file_size_kb,
        width_px       = quality_result.get("width", 0),
        height_px      = quality_result.get("height", 0),
    )

    # ── 5. Behavioural pattern analysis ───────────────────────────────────────
    pattern_result = analyze_patterns(user_id)

    # ── 6. Master risk score ──────────────────────────────────────────────────
    risk_result = calculate_risk_score(
        tamper_score    = tamper_result.get("tamper_score", 0),
        duplicate_score = dup_result.get("duplicate_score", 0),
        quality_score   = quality_result.get("quality_score", 0),
        metadata_score  = meta_result.get("metadata_score", 0),
        pattern_score   = pattern_result.get("pattern_score", 0),
        ocr_confidence  = ocr_confidence,
    )

    # ── Assemble full result ──────────────────────────────────────────────────
    full_result = {
        **quality_result,
        **tamper_result,
        **dup_result,
        "has_exif":        meta_result.get("has_exif", False),
        "exif_software":   meta_result.get("exif_software"),
        "is_screenshot":   meta_result.get("is_screenshot", False) or tamper_result.get("is_screenshot", False),
        "metadata_flags":  meta_result.get("metadata_flags", []),
        "pattern_score":   pattern_result.get("pattern_score", 0),
        "pattern_flags":   pattern_result.get("pattern_flags", []),
        **risk_result,
    }

    # ── 7. Persist ────────────────────────────────────────────────────────────
    fraud_id = _save_fraud_analysis(user_id, document_id, doc_type, full_result)
    if fraud_id:
        _save_risk_score(fraud_id, user_id, document_id, risk_result)
        _save_tamper_flags(fraud_id, tamper_result.get("details", []))

    # ── 8. Update review priority ─────────────────────────────────────────────
    _update_review_priority(user_id, risk_result["risk_level"])

    output = {
        "fraud_id":           fraud_id,
        "risk_level":         risk_result["risk_level"],
        "risk_score":         risk_result["risk_score"],
        "quality_score":      quality_result["quality_score"],
        "quality_grade":      quality_result.get("quality_grade", "UNKNOWN"),
        "duplicate_detected": dup_result["duplicate_detected"],
        "duplicate_score":    dup_result["duplicate_score"],
        "tamper_flags":       tamper_result["tamper_flags"],
        "tamper_score":       tamper_result["tamper_score"],
        "metadata_flags":     meta_result["metadata_flags"],
        "pattern_flags":      pattern_result["pattern_flags"],
        "quality_flags":      quality_result["quality_flags"],
        "recommendation":     risk_result["recommendation"],
        "component_scores":   risk_result["component_scores"],
        "is_screenshot":      full_result["is_screenshot"],
        "blur_class":         quality_result.get("blur_class", "unknown"),
    }

    logger.info(
        "[fraud_engine] Complete: risk=%s score=%d dup=%s tamper_flags=%s",
        output["risk_level"], output["risk_score"],
        output["duplicate_detected"], output["tamper_flags"]
    )
    return output


def get_fraud_analysis(fraud_id: str) -> Optional[Dict]:
    """Fetch a stored fraud analysis by ID."""
    try:
        sb  = get_supabase()
        res = sb.table("fraud_analysis").select("*").eq("id", fraud_id).single().execute()
        return res.data
    except Exception as exc:
        logger.error("[fraud_engine] get_fraud_analysis error: %s", exc)
        return None


def get_user_fraud_history(user_id: int) -> list:
    """All fraud analyses for a user, newest first."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("fraud_analysis")
            .select("*")
            .eq("user_id", user_id)
            .order("analyzed_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[fraud_engine] get_user_fraud_history error: %s", exc)
        return []


def get_high_risk_cases(min_score: int = 50, limit: int = 100) -> list:
    """Fetch all high/critical risk fraud analyses."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("fraud_analysis")
            .select("*, users!inner(full_name, dob)")
            .gte("risk_score", min_score)
            .order("risk_score", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[fraud_engine] get_high_risk_cases error: %s", exc)
        return []


def get_fraud_statistics() -> Dict:
    """Aggregate fraud statistics for dashboard."""
    try:
        sb  = get_supabase()
        res = sb.table("fraud_analysis").select("risk_level, duplicate_detected, is_screenshot, quality_score, tamper_score").execute()
        rows = res.data or []

        total = len(rows)
        if total == 0:
            return {"total": 0}

        by_risk = {}
        for r in rows:
            lvl = r.get("risk_level", "UNKNOWN")
            by_risk[lvl] = by_risk.get(lvl, 0) + 1

        dup_count  = sum(1 for r in rows if r.get("duplicate_detected"))
        ss_count   = sum(1 for r in rows if r.get("is_screenshot"))
        avg_quality = round(sum(r.get("quality_score", 0) for r in rows) / total, 1)
        avg_tamper  = round(sum(r.get("tamper_score", 0) for r in rows) / total, 1)

        return {
            "total":                total,
            "by_risk_level":        by_risk,
            "duplicate_rate":       round(dup_count / total * 100, 1),
            "screenshot_rate":      round(ss_count / total * 100, 1),
            "avg_quality_score":    avg_quality,
            "avg_tamper_score":     avg_tamper,
            "high_risk_count":      by_risk.get("HIGH_RISK", 0) + by_risk.get("CRITICAL_RISK", 0),
            "critical_risk_count":  by_risk.get("CRITICAL_RISK", 0),
        }
    except Exception as exc:
        logger.error("[fraud_engine] get_fraud_statistics error: %s", exc)
        return {}
