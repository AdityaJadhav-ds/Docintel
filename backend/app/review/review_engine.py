"""
app/review/review_engine.py — Master review orchestrator
=========================================================
submit_for_review() is the primary entry point called by validation_service.

Flow:
  1. Receive validation_result from OCR pipeline
  2. Run decision engine → AUTO_APPROVED / REVIEW_REQUIRED / AUTO_REJECTED
  3. Generate correction suggestions
  4. Create review record in Supabase
  5. Log creation to audit trail
  6. Return full review payload
"""

from __future__ import annotations
import json
from typing import Dict, Optional
from datetime import datetime, timezone
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.review.decision_engine import decide_validation_status, build_comparison_payload
from app.review.correction_engine import generate_all_suggestions
from app.review.audit_logger import log_action, log_correction, get_review_history, get_correction_logs
from app.review.reviewer_queue import (
    get_review_by_id, update_review_status, claim_review, unclaim_review,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(obj) -> Dict:
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return {}


# ── Create review record ──────────────────────────────────────────────────────

def _create_review_record(
    user_id:           int,
    doc_type:          str,
    document_id:       Optional[int],
    ocr_confidence:    float,
    validation_result: Dict,
    decision_output:   Dict,
) -> Optional[Dict]:
    """Insert a validation_review row and return it."""
    payload = {
        "user_id":            user_id,
        "document_id":        document_id,
        "doc_type":           doc_type,
        "ocr_confidence":     round(ocr_confidence, 4),
        "validation_result":  _safe(validation_result),
        "decision":           decision_output["decision"],
        "priority":           decision_output["priority"],
        "decision_reasons":   decision_output["reasons"],
        "status":             _initial_status(decision_output["decision"]),
        "created_at":         _now(),
        "updated_at":         _now(),
    }
    try:
        sb  = get_supabase()
        res = sb.table("validation_reviews").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as exc:
        logger.error("[review_engine] _create_review_record error: %s", exc)
        return None


def _initial_status(decision: str) -> str:
    """Map decision to initial queue status."""
    return {
        "AUTO_APPROVED": "approved",
        "AUTO_REJECTED": "rejected",
        "REVIEW_REQUIRED": "pending",
    }.get(decision, "pending")


# ── Public entry point ────────────────────────────────────────────────────────

def submit_for_review(
    user_id:           int,
    doc_type:          str,
    ocr_confidence:    float,
    validation_result: Dict,
    extracted:         Dict,
    document_id:       Optional[int] = None,
) -> Dict:
    """
    Main entry point: evaluate, decide, persist, audit.

    Returns a full review payload:
        {
            "review_id":       str,
            "decision":        str,
            "priority":        int,
            "status":          str,
            "reasons":         list,
            "auto_correctable": bool,
            "comparison":      list,
            "suggestions":     list,
            "created_at":      str,
        }
    """
    logger.info(
        "[review_engine] Submitting review for user_id=%s doc_type=%s confidence=%.3f",
        user_id, doc_type, ocr_confidence
    )

    # 1. Decision engine
    decision_output = decide_validation_status(
        doc_type          = doc_type,
        ocr_confidence    = ocr_confidence,
        validation_result = validation_result,
        extracted         = extracted,
    )

    # 2. Correction suggestions
    comparison  = decision_output.get("comparison", [])
    suggestions = generate_all_suggestions(comparison)

    # 3. Create DB record
    record = _create_review_record(
        user_id           = user_id,
        doc_type          = doc_type,
        document_id       = document_id,
        ocr_confidence    = ocr_confidence,
        validation_result = validation_result,
        decision_output   = decision_output,
    )

    if not record:
        return {
            "success": False,
            "error":   "Failed to create review record in database.",
        }

    review_id = record["id"]

    # 4. Audit log: CREATED
    log_action(
        review_id    = review_id,
        action       = "CREATED",
        actor_id     = "system",
        after_state  = _safe(record),
        reason       = f"Decision: {decision_output['decision']}",
        metadata     = {"reasons": decision_output["reasons"]},
    )

    # 5. Audit log: auto-approved / auto-rejected
    if decision_output["decision"] == "AUTO_APPROVED":
        log_action(review_id=review_id, action="AUTO_APPROVED", actor_id="system",
                   reason="All rules passed — no human review required.")
    elif decision_output["decision"] == "AUTO_REJECTED":
        log_action(review_id=review_id, action="AUTO_REJECTED", actor_id="system",
                   reason="; ".join(decision_output["reasons"][:3]))
    else:
        log_action(review_id=review_id, action="SUBMITTED_FOR_REVIEW", actor_id="system",
                   reason="Uncertain result — queued for human reviewer.")

    return {
        "success":         True,
        "review_id":       review_id,
        "decision":        decision_output["decision"],
        "priority":        decision_output["priority"],
        "status":          record["status"],
        "reasons":         decision_output["reasons"],
        "auto_correctable": decision_output.get("auto_correctable", False),
        "comparison":      comparison,
        "suggestions":     suggestions,
        "overall_status":  decision_output.get("overall_status"),
        "ocr_confidence":  ocr_confidence,
        "created_at":      record["created_at"],
    }


# ── Reviewer action: Approve ──────────────────────────────────────────────────

def approve_review(review_id: str, reviewer_id: str, notes: str = "") -> Dict:
    """Reviewer approves the document — set status to 'approved'."""
    review = get_review_by_id(review_id)
    if not review:
        return {"success": False, "error": "Review not found."}

    before = _safe(review)
    ok     = update_review_status(review_id, "approved", reviewer_id, notes)
    if not ok:
        return {"success": False, "error": "Failed to update review status."}

    log_action(review_id=review_id, action="APPROVED", actor_id=reviewer_id,
               before_state=before,
               after_state={"status": "approved"},
               reason=notes or "Reviewer approved document.")
    return {"success": True, "review_id": review_id, "status": "approved"}


# ── Reviewer action: Reject ───────────────────────────────────────────────────

def reject_review(review_id: str, reviewer_id: str, reason: str = "") -> Dict:
    """Reviewer rejects the document."""
    review = get_review_by_id(review_id)
    if not review:
        return {"success": False, "error": "Review not found."}

    before = _safe(review)
    ok     = update_review_status(review_id, "rejected", reviewer_id, reason)
    if not ok:
        return {"success": False, "error": "Failed to update review status."}

    log_action(review_id=review_id, action="REJECTED", actor_id=reviewer_id,
               before_state=before,
               after_state={"status": "rejected"},
               reason=reason or "Reviewer rejected document.")
    return {"success": True, "review_id": review_id, "status": "rejected"}


# ── Reviewer action: Correct ──────────────────────────────────────────────────

def apply_correction(
    review_id:    str,
    reviewer_id:  str,
    corrections:  Dict,     # {field: new_value}
    notes:        str = "",
) -> Dict:
    """
    Reviewer manually edits one or more extracted field values.

    corrections: {"name": "Nikita Bhagvan Jadhav", "dob": "18/11/2001"}
    """
    review = get_review_by_id(review_id)
    if not review:
        return {"success": False, "error": "Review not found."}

    before_state = _safe(review)
    vr           = review.get("validation_result", {})
    fields       = vr.get("fields", [])
    user_id      = review.get("user_id")

    # Apply corrections to the validation result snapshot
    for field in fields:
        fname = field.get("field")
        if fname in corrections:
            old_val = field.get("extracted")
            new_val = corrections[fname]

            # Log field-level correction
            log_correction(
                review_id         = review_id,
                user_id           = user_id or 0,
                field             = fname,
                old_value         = old_val,
                new_value         = new_val,
                correction_type   = "MANUAL_EDIT",
                confidence_before = field.get("confidence", 0),
                confidence_after  = 95,  # reviewer-confirmed
                corrected_by      = reviewer_id,
            )
            # Update snapshot
            field["extracted"] = new_val
            field["status"]    = "MATCH"
            field["match_score"] = 100

    # Save updated validation_result
    vr["fields"] = fields
    ok = update_review_status(
        review_id    = review_id,
        new_status   = "corrected",
        reviewer_id  = reviewer_id,
        reviewer_notes = notes,
        extra_fields = {"validation_result": _safe(vr)},
    )

    if not ok:
        return {"success": False, "error": "Failed to save corrections."}

    log_action(
        review_id    = review_id,
        action       = "CORRECTED",
        actor_id     = reviewer_id,
        before_state = before_state,
        after_state  = {"corrections": corrections, "status": "corrected"},
        reason       = notes or "Manual field correction applied.",
        metadata     = {"corrected_fields": list(corrections.keys())},
    )
    return {
        "success":    True,
        "review_id":  review_id,
        "status":     "corrected",
        "corrections": corrections,
    }


# ── Reviewer action: Request reprocess ────────────────────────────────────────

def request_reprocess(review_id: str, reviewer_id: str, reason: str = "") -> Dict:
    """Reviewer marks the OCR as failed and requests re-extraction."""
    review = get_review_by_id(review_id)
    if not review:
        return {"success": False, "error": "Review not found."}

    before = _safe(review)
    ok     = update_review_status(review_id, "reprocess_requested", reviewer_id, reason)
    if not ok:
        return {"success": False, "error": "Failed to update status."}

    log_action(review_id=review_id, action="REPROCESS_REQUESTED", actor_id=reviewer_id,
               before_state=before,
               after_state={"status": "reprocess_requested"},
               reason=reason or "Reviewer requested OCR reprocessing.")

    # Enqueue reprocessing
    user_id = review.get("user_id")
    if user_id:
        import asyncio
        try:
            from app.workers.bulk_worker import enqueue_user
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(enqueue_user(user_id))
            else:
                loop.run_until_complete(enqueue_user(user_id))
        except Exception as exc:
            logger.warning("[review_engine] Could not enqueue reprocess: %s", exc)

    return {"success": True, "review_id": review_id, "status": "reprocess_requested",
            "user_id": user_id}


# ── Get full review detail ────────────────────────────────────────────────────

def get_review_detail(review_id: str) -> Dict:
    """Fetch a review with full audit history and correction logs."""
    review = get_review_by_id(review_id)
    if not review:
        return {"success": False, "error": "Review not found."}

    vr           = review.get("validation_result", {})
    comparison   = build_comparison_payload(vr.get("fields", []))
    suggestions  = generate_all_suggestions(comparison)
    history      = get_review_history(review_id)
    corrections  = get_correction_logs(review_id)

    return {
        "success":     True,
        "review":      review,
        "comparison":  comparison,
        "suggestions": suggestions,
        "history":     history,
        "corrections": corrections,
    }
