"""
app/api/review_routes.py — FastAPI review endpoints
====================================================
All human review, correction, queue, and export endpoints.
"""

from __future__ import annotations
import csv
import io
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse

from app.core.logger import logger
from app.review.review_engine import (
    submit_for_review, approve_review, reject_review,
    apply_correction, request_reprocess, get_review_detail,
)
from app.review.reviewer_queue import (
    fetch_queue, get_reviews_for_user, get_queue_stats,
    bulk_approve, bulk_reject, claim_review, unclaim_review,
)
from app.review.audit_logger import get_review_history, get_correction_logs
from app.schemas.review_schema import (
    ApproveRequest, RejectRequest, CorrectRequest,
    ReprocessRequest, ClaimRequest,
    BulkApproveRequest, BulkRejectRequest,
)

router = APIRouter(prefix="/review", tags=["Review"])


# ── Queue ─────────────────────────────────────────────────────────────────────

@router.get("/queue")
def get_review_queue(
    status:    Optional[str] = Query(None),
    doc_type:  Optional[str] = Query(None),
    decision:  Optional[str] = Query(None),
    priority:  Optional[int] = Query(None),
    page:      int           = Query(1, ge=1),
    page_size: int           = Query(20, ge=1, le=100),
    sort_by:   str           = Query("priority"),
    sort_desc: bool          = Query(False),
):
    """Fetch the review queue with filters, pagination, and sorting."""
    return fetch_queue(
        status=status, doc_type=doc_type, decision=decision,
        priority=priority, page=page, page_size=page_size,
        sort_by=sort_by, sort_desc=sort_desc,
    )


@router.get("/queue/stats")
def queue_stats():
    """Queue health stats: by status, priority, decision."""
    return get_queue_stats()


@router.get("/user/{user_id}")
def reviews_for_user(user_id: int):
    """All reviews for a specific user."""
    reviews = get_reviews_for_user(user_id)
    return {"success": True, "user_id": user_id, "reviews": reviews, "total": len(reviews)}


# ── Single review ─────────────────────────────────────────────────────────────

@router.get("/{review_id}")
def get_review(review_id: str):
    """Get full review detail including comparison, suggestions, history."""
    result = get_review_detail(review_id)
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "Review not found."))
    return result


@router.get("/{review_id}/history")
def review_history(review_id: str):
    """Immutable audit trail for a review."""
    history = get_review_history(review_id)
    return {"review_id": review_id, "history": history, "total": len(history)}


@router.get("/{review_id}/corrections")
def review_corrections(review_id: str):
    """All field-level corrections made on a review."""
    corrections = get_correction_logs(review_id)
    return {"review_id": review_id, "corrections": corrections}


# ── Claim / unclaim ───────────────────────────────────────────────────────────

@router.post("/{review_id}/claim")
def claim(review_id: str, body: ClaimRequest):
    """Claim a review for exclusive editing (optimistic lock)."""
    success = claim_review(review_id, body.reviewer_id)
    if not success:
        raise HTTPException(409, "Review already claimed or not available.")
    return {"success": True, "review_id": review_id, "claimed_by": body.reviewer_id}


@router.post("/{review_id}/unclaim")
def unclaim(review_id: str, body: ClaimRequest):
    """Release a claimed review back to the queue."""
    success = unclaim_review(review_id, body.reviewer_id)
    return {"success": success, "review_id": review_id}


# ── Reviewer actions ──────────────────────────────────────────────────────────

@router.post("/{review_id}/approve")
def approve(review_id: str, body: ApproveRequest):
    """Reviewer approves a document."""
    result = approve_review(review_id, body.reviewer_id, body.notes or "")
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/{review_id}/reject")
def reject(review_id: str, body: RejectRequest):
    """Reviewer rejects a document."""
    result = reject_review(review_id, body.reviewer_id, body.reason or "")
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/{review_id}/correct")
def correct(review_id: str, body: CorrectRequest):
    """Reviewer manually corrects one or more extracted field values."""
    if not body.corrections:
        raise HTTPException(400, "No corrections provided.")
    result = apply_correction(review_id, body.reviewer_id, body.corrections, body.notes or "")
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result


@router.post("/{review_id}/reprocess")
def reprocess(review_id: str, body: ReprocessRequest):
    """Reviewer marks OCR as failed and triggers re-extraction."""
    result = request_reprocess(review_id, body.reviewer_id, body.reason or "")
    if not result.get("success"):
        raise HTTPException(400, result.get("error"))
    return result


# ── Bulk operations ───────────────────────────────────────────────────────────

@router.post("/bulk/approve")
def bulk_approve_endpoint(body: BulkApproveRequest):
    """Batch approve multiple reviews."""
    if not body.review_ids:
        raise HTTPException(400, "No review IDs provided.")
    result = bulk_approve(body.review_ids, body.reviewer_id)
    return {
        "success": True,
        "approved_count": len(result["approved"]),
        "failed_count":   len(result["failed"]),
        **result,
    }


@router.post("/bulk/reject")
def bulk_reject_endpoint(body: BulkRejectRequest):
    """Batch reject multiple reviews."""
    if not body.review_ids:
        raise HTTPException(400, "No review IDs provided.")
    result = bulk_reject(body.review_ids, body.reviewer_id, body.reason or "")
    return {
        "success": True,
        "rejected_count": len(result["rejected"]),
        "failed_count":   len(result["failed"]),
        **result,
    }


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export/json")
def export_json(
    status:   Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    page:     int           = Query(1),
    page_size:int           = Query(500, le=1000),
):
    """Export review queue as JSON."""
    data = fetch_queue(status=status, doc_type=doc_type, page=page, page_size=page_size)
    return JSONResponse(content=data)


@router.get("/export/csv")
def export_csv(
    status:   Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
):
    """Export review queue as downloadable CSV."""
    data = fetch_queue(status=status, doc_type=doc_type, page=1, page_size=1000)
    items = data.get("items", [])

    output = io.StringIO()
    fieldnames = [
        "id", "user_id", "doc_type", "decision", "priority",
        "status", "ocr_confidence", "reviewer_id", "created_at", "reviewed_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        writer.writerow(item)

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=review_export.csv"},
    )
