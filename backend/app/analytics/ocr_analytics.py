"""
app/analytics/ocr_analytics.py — OCR performance intelligence
=============================================================
Tracks accuracy, confidence trends, failure patterns, and doc-type breakdown.
"""

from __future__ import annotations
from typing import Dict, List
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.analytics.metrics_engine import (
    get_avg_ocr_confidence, get_verification_stats,
    get_daily_counts, _days_ago, _now,
)


def get_ocr_success_rate(period: str = "week") -> Dict:
    """OCR success rate — counts VERIFIED vs OCR_FAILED in verified_data."""
    stats = get_verification_stats(period)
    total = stats.get("total", 0)
    if total == 0:
        return {"success_rate": 0.0, "failure_rate": 0.0, "total": 0}
    failed      = stats.get("ocr_failed", 0)
    verified    = stats.get("verified", 0)
    return {
        "success_rate":     round((total - failed) / total * 100, 2),
        "failure_rate":     round(failed / total * 100, 2),
        "verified_rate":    round(verified / total * 100, 2),
        "total":            total,
        "ocr_failed":       failed,
        "verified":         verified,
        "mismatch":         stats.get("mismatch", 0),
        "avg_confidence":   get_avg_ocr_confidence(period),
    }


def get_confidence_distribution(period: str = "week") -> Dict:
    """Bucket extracted_data by confidence score band."""
    try:
        sb   = get_supabase()
        from app.analytics.metrics_engine import _period_start
        q    = sb.table("extracted_data").select("confidence_score, doc_type")
        if period != "all":
            q = q.gte("processed_at", _period_start(period))
        rows = q.execute().data or []
        bands = {"0-40": 0, "41-70": 0, "71-85": 0, "86-100": 0}
        doc_confidence: Dict[str, List[float]] = {}
        for r in rows:
            conf = float(r.get("confidence_score") or 0)
            dt   = r.get("doc_type", "unknown")
            # Band
            if conf <= 0.40:   bands["0-40"]   += 1
            elif conf <= 0.70: bands["41-70"]  += 1
            elif conf <= 0.85: bands["71-85"]  += 1
            else:              bands["86-100"] += 1
            doc_confidence.setdefault(dt, []).append(conf)
        by_doc_type = {
            dt: round(sum(v)/len(v), 4)
            for dt, v in doc_confidence.items() if v
        }
        return {
            "bands":       bands,
            "by_doc_type": by_doc_type,
            "total":       len(rows),
        }
    except Exception as exc:
        logger.debug("[ocr_analytics] confidence_distribution error: %s", exc)
        return {}


def get_doc_type_breakdown(period: str = "week") -> Dict:
    """Split document counts by Aadhaar vs PAN."""
    try:
        sb = get_supabase()
        from app.analytics.metrics_engine import _period_start
        q  = sb.table("extracted_data").select("doc_type")
        if period != "all":
            q = q.gte("processed_at", _period_start(period))
        rows  = q.execute().data or []
        total = len(rows)
        counts: Dict[str, int] = {}
        for r in rows:
            dt = r.get("doc_type", "unknown")
            counts[dt] = counts.get(dt, 0) + 1
        return {
            "total":   total,
            "counts":  counts,
            "rates":   {dt: round(c/max(total,1)*100,2) for dt, c in counts.items()},
        }
    except Exception as exc:
        logger.debug("[ocr_analytics] doc_type_breakdown error: %s", exc)
        return {}


def get_ocr_failure_trend(days: int = 14) -> List[Dict]:
    """Daily OCR failure counts for trend chart."""
    return get_daily_counts("verified_data", "verified_at", days,
                             filters=[("status", "OCR_FAILED")])


def get_ocr_analytics(period: str = "week", trend_days: int = 14) -> Dict:
    """Full OCR analytics bundle."""
    return {
        "success_rate":       get_ocr_success_rate(period),
        "confidence_dist":    get_confidence_distribution(period),
        "doc_type_breakdown": get_doc_type_breakdown(period),
        "failure_trend":      get_ocr_failure_trend(trend_days),
    }
