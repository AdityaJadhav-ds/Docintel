"""
app/analytics/reviewer_analytics.py — Reviewer productivity intelligence
========================================================================
Tracks per-reviewer performance, queue backlog, and leaderboard.
"""

from __future__ import annotations
from typing import Dict, List, Optional
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.analytics.metrics_engine import _period_start, _days_ago


def get_reviewer_stats(reviewer_id: Optional[str] = None, period: str = "week") -> List[Dict]:
    """
    Per-reviewer: reviews completed, approved, rejected, corrected.
    If reviewer_id given, returns only that reviewer.
    """
    try:
        sb = get_supabase()
        q  = (
            sb.table("validation_reviews")
            .select("reviewer_id, status, reviewed_at, created_at")
            .not_.is_("reviewer_id", "null")
        )
        if period != "all":
            q = q.gte("reviewed_at", _period_start(period))
        if reviewer_id:
            q = q.eq("reviewer_id", reviewer_id)
        rows = q.execute().data or []

        by_reviewer: Dict[str, Dict] = {}
        for r in rows:
            rid    = r.get("reviewer_id", "unknown")
            status = r.get("status", "unknown")
            entry  = by_reviewer.setdefault(rid, {
                "reviewer_id": rid, "total": 0, "approved": 0,
                "rejected": 0, "corrected": 0, "reprocessed": 0,
            })
            entry["total"] += 1
            if status == "approved":    entry["approved"]    += 1
            if status == "rejected":    entry["rejected"]    += 1
            if status == "corrected":   entry["corrected"]   += 1
            if status == "reprocess_requested": entry["reprocessed"] += 1

        result = list(by_reviewer.values())
        for r in result:
            total = max(r["total"], 1)
            r["approval_rate"]   = round(r["approved"] / total * 100, 2)
            r["rejection_rate"]  = round(r["rejected"] / total * 100, 2)
            r["correction_rate"] = round(r["corrected"] / total * 100, 2)
        result.sort(key=lambda x: x["total"], reverse=True)
        return result
    except Exception as exc:
        logger.debug("[reviewer_analytics] get_reviewer_stats error: %s", exc)
        return []


def get_reviewer_leaderboard(period: str = "week", top_n: int = 10) -> List[Dict]:
    """Top reviewers by volume + productivity score."""
    stats = get_reviewer_stats(period=period)[:top_n]
    for i, r in enumerate(stats):
        # Productivity score: 40% volume + 30% approval rate + 30% low correction rate
        volume_score = min(100, r["total"] * 5)
        correction_penalty = r["correction_rate"] * 0.5
        productivity = 0.40 * volume_score + 0.30 * r["approval_rate"] - 0.30 * correction_penalty
        r["productivity_score"] = round(max(0, min(100, productivity)), 1)
        r["rank"] = i + 1
    return stats


def get_queue_backlog() -> Dict:
    """Current review queue depth split by priority and decision."""
    try:
        sb   = get_supabase()
        try:
            rows = (
                sb.table("validation_reviews")
                .select("priority, decision, status")
                .in_("status", ["pending", "in_review"])
                .execute()
            ).data or []
            total   = len(rows)
            p1      = sum(1 for r in rows if r.get("priority") == 1)
            p2      = sum(1 for r in rows if r.get("priority") == 2)
            p3      = sum(1 for r in rows if r.get("priority") == 3)
            in_rev  = sum(1 for r in rows if r.get("status") == "in_review")
            overloaded = total > 200 or p1 > 50
            return {
                "total_pending":      total,
                "high_priority":      p1,
                "medium_priority":    p2,
                "low_priority":       p3,
                "being_reviewed":     in_rev,
                "awaiting_review":    total - in_rev,
                "overloaded":         overloaded,
            }
        except Exception as e:
            if "PGRST205" in str(e):
                logger.debug("[reviewer_analytics] validation_reviews not found, falling back to verified_data")
                rows = (
                    sb.table("verified_data")
                    .select("status")
                    .in_("status", ["needs_review", "REVIEW_REQUIRED", "PENDING"])
                    .execute()
                ).data or []
                total = len(rows)
                return {
                    "total_pending": total,
                    "high_priority": 0,
                    "medium_priority": 0,
                    "low_priority": 0,
                    "being_reviewed": 0,
                    "awaiting_review": total,
                    "overloaded": total > 200,
                }
            raise e
    except Exception as exc:
        logger.debug("[reviewer_analytics] get_queue_backlog error: %s", exc)
        return {}


def get_correction_frequency(period: str = "week") -> Dict:
    """How often reviewers need to correct OCR values."""
    try:
        sb    = get_supabase()
        q     = sb.table("correction_logs").select("field, correction_type, corrected_by")
        if period != "all":
            q = q.gte("created_at", _period_start(period))
        rows  = q.execute().data or []
        total = len(rows)
        by_field: Dict[str, int]  = {}
        by_type:  Dict[str, int]  = {}
        for r in rows:
            f = r.get("field", "unknown")
            t = r.get("correction_type", "unknown")
            by_field[f] = by_field.get(f, 0) + 1
            by_type[t]  = by_type.get(t, 0) + 1
        return {
            "total_corrections": total,
            "by_field":         by_field,
            "by_type":          by_type,
            "most_corrected":   max(by_field, key=by_field.get, default="none") if by_field else "none",
        }
    except Exception as exc:
        logger.debug("[reviewer_analytics] get_correction_frequency error: %s", exc)
        return {}


def get_reviewer_analytics(period: str = "week") -> Dict:
    """Full reviewer analytics bundle."""
    return {
        "leaderboard":        get_reviewer_leaderboard(period),
        "queue_backlog":      get_queue_backlog(),
        "correction_frequency": get_correction_frequency(period),
        "total_reviewers":    len(get_reviewer_stats(period=period)),
    }
