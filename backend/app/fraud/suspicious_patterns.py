"""
app/fraud/suspicious_patterns.py — Behavioural pattern analysis
===============================================================
Detects suspicious upload and identity patterns:
  1. Repeated OCR failures — same user keeps failing
  2. High upload frequency — bulk-uploading in short windows
  3. Same document reused across different users
  4. Multiple different documents for same user in short time
  5. Repeated rejection history
  6. Cross-user same-name patterns (possible identity farm)
"""

from __future__ import annotations
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from app.core.logger import logger
from app.core.supabase_client import get_supabase


# ── Thresholds ────────────────────────────────────────────────────────────────

MAX_UPLOADS_PER_HOUR   = 5
MAX_OCR_FAILURES       = 3
MAX_REJECTIONS         = 2
SAME_NAME_USER_LIMIT   = 3     # how many users with same name → suspicious


# ── Individual pattern checks ─────────────────────────────────────────────────

def _check_upload_frequency(user_id: int) -> Dict:
    """Flag if user uploaded more than MAX_UPLOADS_PER_HOUR in last 1 hour."""
    try:
        sb      = get_supabase()
        cutoff  = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        res     = (
            sb.table("documents")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("uploaded_at", cutoff)
            .execute()
        )
        count = res.count or 0
        suspicious = count > MAX_UPLOADS_PER_HOUR
        return {
            "check":      "upload_frequency",
            "value":      count,
            "threshold":  MAX_UPLOADS_PER_HOUR,
            "suspicious": suspicious,
            "flag":       "high_upload_frequency" if suspicious else None,
        }
    except Exception as exc:
        logger.debug("[suspicious_patterns] upload_frequency error: %s", exc)
        return {"check": "upload_frequency", "suspicious": False, "flag": None}


def _check_repeated_ocr_failures(user_id: int) -> Dict:
    """Flag if user has multiple OCR_FAILED results."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("verified_data")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("status", "OCR_FAILED")
            .execute()
        )
        count = res.count or 0
        suspicious = count >= MAX_OCR_FAILURES
        return {
            "check":      "repeated_ocr_failures",
            "value":      count,
            "threshold":  MAX_OCR_FAILURES,
            "suspicious": suspicious,
            "flag":       "repeated_ocr_failures" if suspicious else None,
        }
    except Exception as exc:
        logger.debug("[suspicious_patterns] ocr_failures error: %s", exc)
        return {"check": "repeated_ocr_failures", "suspicious": False, "flag": None}


def _check_review_rejections(user_id: int) -> Dict:
    """Flag if user has been rejected multiple times."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("validation_reviews")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("status", "rejected")
            .execute()
        )
        count = res.count or 0
        suspicious = count >= MAX_REJECTIONS
        return {
            "check":      "repeated_rejections",
            "value":      count,
            "threshold":  MAX_REJECTIONS,
            "suspicious": suspicious,
            "flag":       "repeated_document_rejections" if suspicious else None,
        }
    except Exception as exc:
        logger.debug("[suspicious_patterns] rejections error: %s", exc)
        return {"check": "repeated_rejections", "suspicious": False, "flag": None}


def _check_same_name_pattern(user_id: int) -> Dict:
    """
    Check if many users have the same full_name.
    Possible synthetic identity farm indicator.
    """
    try:
        sb = get_supabase()
        # Fetch this user's name
        user_res = sb.table("users").select("full_name").eq("id", user_id).single().execute()
        if not user_res.data:
            return {"check": "same_name_pattern", "suspicious": False, "flag": None}
        full_name = (user_res.data.get("full_name") or "").strip()
        if not full_name or len(full_name.split()) < 2:
            return {"check": "same_name_pattern", "suspicious": False, "flag": None}

        # Count users with the same name
        count_res = (
            sb.table("users")
            .select("id", count="exact")
            .ilike("full_name", full_name)
            .neq("id", user_id)
            .execute()
        )
        count = count_res.count or 0
        suspicious = count >= SAME_NAME_USER_LIMIT
        return {
            "check":      "same_name_pattern",
            "value":      count,
            "threshold":  SAME_NAME_USER_LIMIT,
            "suspicious": suspicious,
            "flag":       "multiple_users_same_name" if suspicious else None,
            "name":       full_name,
        }
    except Exception as exc:
        logger.debug("[suspicious_patterns] same_name error: %s", exc)
        return {"check": "same_name_pattern", "suspicious": False, "flag": None}


def _check_duplicate_flag_history(user_id: int) -> Dict:
    """Check if this user already has duplicate match records."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("duplicate_matches")
            .select("id", count="exact")
            .eq("source_user_id", user_id)
            .execute()
        )
        count      = res.count or 0
        suspicious = count > 0
        return {
            "check":      "prior_duplicate_flags",
            "value":      count,
            "suspicious": suspicious,
            "flag":       "prior_duplicate_match_history" if suspicious else None,
        }
    except Exception as exc:
        logger.debug("[suspicious_patterns] duplicate_history error: %s", exc)
        return {"check": "prior_duplicate_flags", "suspicious": False, "flag": None}


# ── Pattern score combiner ────────────────────────────────────────────────────

def _compute_pattern_score(checks: List[Dict]) -> int:
    """Sum suspicion scores from each check."""
    score_map = {
        "high_upload_frequency":             25,
        "repeated_ocr_failures":             20,
        "repeated_document_rejections":      30,
        "multiple_users_same_name":          20,
        "prior_duplicate_match_history":     40,
    }
    total = 0
    for check in checks:
        flag = check.get("flag")
        if flag and flag in score_map:
            total += score_map[flag]
    return min(100, total)


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_patterns(user_id: int) -> Dict:
    """
    Run all behavioural pattern checks for a user.

    Returns:
        {
            "pattern_score":    int (0-100),
            "pattern_flags":    [str],
            "checks":           [detailed check results],
            "is_suspicious":    bool,
        }
    """
    checks = [
        _check_upload_frequency(user_id),
        _check_repeated_ocr_failures(user_id),
        _check_review_rejections(user_id),
        _check_same_name_pattern(user_id),
        _check_duplicate_flag_history(user_id),
    ]

    pattern_flags = [c["flag"] for c in checks if c.get("flag")]
    pattern_score = _compute_pattern_score(checks)
    is_suspicious = pattern_score >= 25 or len(pattern_flags) >= 2

    logger.info(
        "[suspicious_patterns] user_id=%s score=%d flags=%s",
        user_id, pattern_score, pattern_flags
    )

    return {
        "pattern_score":  pattern_score,
        "pattern_flags":  pattern_flags,
        "checks":         checks,
        "is_suspicious":  is_suspicious,
    }
