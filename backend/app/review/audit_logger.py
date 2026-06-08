"""
app/review/audit_logger.py — Immutable audit trail system
=========================================================
Appends to review_history table — never updates, never deletes.
Every state change in a review lifecycle is recorded here.

Actions:
  CREATED              — review record first created
  AUTO_APPROVED        — decision engine approved automatically
  AUTO_REJECTED        — decision engine rejected automatically
  SUBMITTED_FOR_REVIEW — sent to human reviewer queue
  APPROVED             — reviewer approved
  REJECTED             — reviewer rejected
  CORRECTED            — reviewer edited one or more fields
  REPROCESS_REQUESTED  — reviewer requested re-OCR
  REPROCESSING         — system started reprocessing
  STATUS_CHANGED       — generic status lifecycle event
"""

from __future__ import annotations
import json
from typing import Dict, Optional, Any
from datetime import datetime, timezone
from app.core.logger import logger
from app.core.supabase_client import get_supabase


# ── Helper ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(obj: Any) -> Dict:
    """Ensure obj is JSON-serializable dict."""
    if isinstance(obj, dict):
        return obj
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {}


# ── Public API ────────────────────────────────────────────────────────────────

def log_action(
    review_id:    str,
    action:       str,
    actor_id:     str = "system",
    before_state: Optional[Dict] = None,
    after_state:  Optional[Dict] = None,
    reason:       Optional[str]  = None,
    metadata:     Optional[Dict] = None,
) -> bool:
    """
    Append an immutable audit record to review_history.

    Args:
        review_id:    UUID of the validation_review record
        action:       One of the action constants above
        actor_id:     Reviewer UID or 'system'
        before_state: Snapshot before the change
        after_state:  Snapshot after the change
        reason:       Human-readable reason
        metadata:     Extra context (e.g., field names changed)

    Returns:
        True on success, False on failure (never raises).
    """
    payload = {
        "review_id":    review_id,
        "action":       action,
        "actor_id":     actor_id,
        "before_state": _safe_json(before_state or {}),
        "after_state":  _safe_json(after_state or {}),
        "reason":       reason or "",
        "metadata":     _safe_json(metadata or {}),
        "created_at":   _now_iso(),
    }
    try:
        sb = get_supabase()
        sb.table("review_history").insert(payload).execute()
        logger.info(
            "[audit_logger] action=%s review_id=%s actor=%s",
            action, review_id, actor_id
        )
        return True
    except Exception as exc:
        logger.error("[audit_logger] Failed to log action=%s: %s", action, exc)
        return False


def log_correction(
    review_id:         str,
    user_id:           int,
    field:             str,
    old_value:         Optional[str],
    new_value:         Optional[str],
    correction_type:   str,
    confidence_before: int = 0,
    confidence_after:  int = 0,
    corrected_by:      str = "reviewer",
) -> bool:
    """
    Append a field-level correction to correction_logs.
    Called once per corrected field.
    """
    payload = {
        "review_id":         review_id,
        "user_id":           user_id,
        "field":             field,
        "old_value":         old_value,
        "new_value":         new_value,
        "correction_type":   correction_type,
        "confidence_before": confidence_before,
        "confidence_after":  confidence_after,
        "corrected_by":      corrected_by,
        "created_at":        _now_iso(),
    }
    try:
        sb = get_supabase()
        sb.table("correction_logs").insert(payload).execute()
        logger.info(
            "[audit_logger] correction field=%s %r→%r review_id=%s",
            field, old_value, new_value, review_id
        )
        return True
    except Exception as exc:
        logger.error("[audit_logger] Failed to log correction field=%s: %s", field, exc)
        return False


def get_review_history(review_id: str) -> list:
    """Fetch the full audit trail for a review, ordered by time."""
    try:
        sb = get_supabase()
        res = (
            sb.table("review_history")
            .select("*")
            .eq("review_id", review_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[audit_logger] get_review_history failed: %s", exc)
        return []


def get_correction_logs(review_id: str) -> list:
    """Fetch all field corrections for a review."""
    try:
        sb = get_supabase()
        res = (
            sb.table("correction_logs")
            .select("*")
            .eq("review_id", review_id)
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[audit_logger] get_correction_logs failed: %s", exc)
        return []
