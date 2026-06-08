"""
app/review/reviewer_queue.py — Review queue management
=======================================================
Manages the reviewer queue with:
  - Priority-ordered fetching (HIGH first)
  - Pagination support
  - Filtering (status, doc_type, decision, priority)
  - Claim/unclaim for concurrent reviewers (optimistic locking)
  - Bulk operations
"""

from __future__ import annotations
from typing import Dict, List, Optional
from app.core.logger import logger
from app.core.supabase_client import get_supabase


# ── Fetch queue ───────────────────────────────────────────────────────────────

def fetch_queue(
    status:    Optional[str] = None,
    doc_type:  Optional[str] = None,
    decision:  Optional[str] = None,
    priority:  Optional[int] = None,
    page:      int = 1,
    page_size: int = 20,
    sort_by:   str = "priority",
    sort_desc: bool = False,
) -> Dict:
    """
    Fetch review queue with filtering, pagination, sorting.

    Returns:
        {
            "items":      [...],
            "total":      int,
            "page":       int,
            "page_size":  int,
            "total_pages": int,
        }
    """
    try:
        sb = get_supabase()
        query = sb.table("validation_reviews").select(
            "*, users!inner(full_name, dob)",
            count="exact"
        )

        # Apply filters
        if status:
            query = query.eq("status", status)
        else:
            query = query.in_("status", ["pending", "in_review"])
        if doc_type:
            query = query.eq("doc_type", doc_type)
        if decision:
            query = query.eq("decision", decision)
        if priority is not None:
            query = query.eq("priority", priority)

        # Sort
        query = query.order(sort_by, desc=sort_desc)
        if sort_by != "created_at":
            query = query.order("created_at", desc=False)

        # Paginate
        offset = (page - 1) * page_size
        query  = query.range(offset, offset + page_size - 1)

        res   = query.execute()
        total = res.count or 0

        return {
            "items":       res.data or [],
            "total":       total,
            "page":        page,
            "page_size":   page_size,
            "total_pages": max(1, -(-total // page_size)),
        }
    except Exception as exc:
        logger.error("[reviewer_queue] fetch_queue error: %s", exc)
        return {"items": [], "total": 0, "page": page, "page_size": page_size, "total_pages": 0}


def get_review_by_id(review_id: str) -> Optional[Dict]:
    try:
        sb  = get_supabase()
        res = sb.table("validation_reviews").select("*").eq("id", review_id).single().execute()
        return res.data
    except Exception as exc:
        logger.error("[reviewer_queue] get_review_by_id %s error: %s", review_id, exc)
        return None


def get_reviews_for_user(user_id: int) -> List[Dict]:
    try:
        sb  = get_supabase()
        res = (
            sb.table("validation_reviews")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[reviewer_queue] get_reviews_for_user error: %s", exc)
        return []


# ── Claim / unclaim ────────────────────────────────────────────────────────────

def claim_review(review_id: str, reviewer_id: str) -> bool:
    """
    Mark a review as 'in_review' by a specific reviewer.
    Only succeeds if currently 'pending' (optimistic lock).
    """
    try:
        sb = get_supabase()
        res = (
            sb.table("validation_reviews")
            .update({"status": "in_review", "reviewer_id": reviewer_id})
            .eq("id", review_id)
            .eq("status", "pending")     # ← optimistic lock
            .execute()
        )
        success = bool(res.data)
        if success:
            logger.info("[reviewer_queue] Claimed review_id=%s by %s", review_id, reviewer_id)
        else:
            logger.warning("[reviewer_queue] Could not claim review_id=%s (already claimed?)", review_id)
        return success
    except Exception as exc:
        logger.error("[reviewer_queue] claim_review error: %s", exc)
        return False


def unclaim_review(review_id: str, reviewer_id: str) -> bool:
    """Release a claimed review back to 'pending'."""
    try:
        sb = get_supabase()
        res = (
            sb.table("validation_reviews")
            .update({"status": "pending", "reviewer_id": None})
            .eq("id", review_id)
            .eq("reviewer_id", reviewer_id)
            .execute()
        )
        return bool(res.data)
    except Exception as exc:
        logger.error("[reviewer_queue] unclaim_review error: %s", exc)
        return False


# ── Status updates ─────────────────────────────────────────────────────────────

def update_review_status(
    review_id:      str,
    new_status:     str,
    reviewer_id:    Optional[str] = None,
    reviewer_notes: Optional[str] = None,
    extra_fields:   Optional[Dict] = None,
) -> bool:
    from datetime import datetime, timezone
    payload: Dict = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if reviewer_id:
        payload["reviewer_id"]   = reviewer_id
        payload["reviewed_at"]   = datetime.now(timezone.utc).isoformat()
    if reviewer_notes:
        payload["reviewer_notes"] = reviewer_notes
    if extra_fields:
        payload.update(extra_fields)
    try:
        sb = get_supabase()
        res = sb.table("validation_reviews").update(payload).eq("id", review_id).execute()
        return bool(res.data)
    except Exception as exc:
        logger.error("[reviewer_queue] update_review_status error: %s", exc)
        return False


# ── Bulk operations ────────────────────────────────────────────────────────────

def bulk_approve(review_ids: List[str], reviewer_id: str) -> Dict:
    """Batch approve a list of review IDs."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    approved, failed = [], []
    sb = get_supabase()
    for rid in review_ids:
        try:
            res = (
                sb.table("validation_reviews")
                .update({"status": "approved", "reviewer_id": reviewer_id,
                         "reviewed_at": now, "updated_at": now})
                .eq("id", rid)
                .execute()
            )
            (approved if res.data else failed).append(rid)
        except Exception:
            failed.append(rid)
    return {"approved": approved, "failed": failed}


def bulk_reject(review_ids: List[str], reviewer_id: str, reason: str = "") -> Dict:
    """Batch reject a list of review IDs."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    rejected, failed = [], []
    sb = get_supabase()
    for rid in review_ids:
        try:
            res = (
                sb.table("validation_reviews")
                .update({"status": "rejected", "reviewer_id": reviewer_id,
                         "reviewer_notes": reason, "reviewed_at": now, "updated_at": now})
                .eq("id", rid)
                .execute()
            )
            (rejected if res.data else failed).append(rid)
        except Exception:
            failed.append(rid)
    return {"rejected": rejected, "failed": failed}


# ── Queue stats ───────────────────────────────────────────────────────────────

def get_queue_stats() -> Dict:
    """Return queue health stats by status and priority."""
    try:
        sb  = get_supabase()
        res = sb.table("validation_reviews").select("status, priority, decision").execute()
        rows = res.data or []

        stats: Dict = {
            "total":             len(rows),
            "by_status":         {},
            "by_priority":       {1: 0, 2: 0, 3: 0},
            "by_decision":       {},
        }
        for r in rows:
            s = r.get("status", "unknown")
            d = r.get("decision", "unknown")
            p = r.get("priority", 2)
            stats["by_status"][s]   = stats["by_status"].get(s, 0) + 1
            stats["by_decision"][d] = stats["by_decision"].get(d, 0) + 1
            stats["by_priority"][p] = stats["by_priority"].get(p, 0) + 1
        return stats
    except Exception as exc:
        logger.error("[reviewer_queue] get_queue_stats error: %s", exc)
        return {}
