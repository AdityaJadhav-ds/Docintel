"""
app/analytics/fraud_analytics.py — Fraud intelligence & trend tracking
======================================================================
"""

from __future__ import annotations
from typing import Dict, List
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.analytics.metrics_engine import (
    get_fraud_summary_counts, get_daily_counts, _period_start,
)


def get_risk_distribution(period: str = "all") -> Dict:
    """Risk level breakdown with percentages."""
    summary = get_fraud_summary_counts(period)
    total   = max(summary.get("total", 0), 1)
    by_risk = summary.get("by_risk_level", {})
    return {
        "total":         total,
        "distribution":  by_risk,
        "rates": {
            lvl: round(cnt / total * 100, 2)
            for lvl, cnt in by_risk.items()
        },
        "high_risk_rate":     summary.get("fraud_rate", 0),
        "duplicate_rate":     summary.get("duplicate_rate", 0),
        "critical_rate":      round(by_risk.get("CRITICAL_RISK", 0) / total * 100, 2),
    }


def get_top_risky_users(limit: int = 10) -> List[Dict]:
    """Users with highest risk scores — potential fraud actors."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("fraud_analysis")
            .select("user_id, risk_score, risk_level, duplicate_detected, tamper_score")
            .gte("risk_score", 50)
            .order("risk_score", desc=True)
            .limit(limit)
            .execute()
        )
        # Deduplicate by user_id (keep highest score)
        seen: Dict[int, Dict] = {}
        for r in (res.data or []):
            uid = r.get("user_id")
            if uid not in seen or r["risk_score"] > seen[uid]["risk_score"]:
                seen[uid] = r
        return list(seen.values())[:limit]
    except Exception as exc:
        logger.debug("[fraud_analytics] get_top_risky_users error: %s", exc)
        return []


def get_duplicate_attack_trend(days: int = 14) -> List[Dict]:
    """Daily duplicate detection counts for trend chart."""
    try:
        sb    = get_supabase()
        from app.analytics.metrics_engine import _days_ago
        since = _days_ago(days)
        rows  = (
            sb.table("fraud_analysis")
            .select("analyzed_at, duplicate_detected")
            .gte("analyzed_at", since)
            .execute()
        ).data or []

        from datetime import timedelta, timezone
        from app.analytics.metrics_engine import _now
        bucket: Dict[str, int] = {}
        for r in rows:
            if r.get("duplicate_detected"):
                day = str(r.get("analyzed_at", ""))[:10]
                bucket[day] = bucket.get(day, 0) + 1
        result = []
        for i in range(days - 1, -1, -1):
            d = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
            result.append({"date": d, "duplicate_count": bucket.get(d, 0)})
        return result
    except Exception as exc:
        logger.debug("[fraud_analytics] duplicate_attack_trend error: %s", exc)
        return []


def get_fraud_trend(days: int = 14) -> List[Dict]:
    """Daily high-risk case counts."""
    try:
        sb    = get_supabase()
        from app.analytics.metrics_engine import _days_ago, _now
        from datetime import timedelta
        since = _days_ago(days)
        rows  = (
            sb.table("fraud_analysis")
            .select("analyzed_at, risk_level, risk_score")
            .gte("analyzed_at", since)
            .execute()
        ).data or []
        bucket: Dict[str, Dict] = {}
        for r in rows:
            day  = str(r.get("analyzed_at", ""))[:10]
            b    = bucket.setdefault(day, {"total": 0, "high_risk": 0, "avg_score": []})
            b["total"] += 1
            if r.get("risk_level") in ("HIGH_RISK", "CRITICAL_RISK"):
                b["high_risk"] += 1
            b["avg_score"].append(r.get("risk_score", 0))
        result = []
        for i in range(days - 1, -1, -1):
            d = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
            b = bucket.get(d, {"total": 0, "high_risk": 0, "avg_score": []})
            scores = b["avg_score"]
            result.append({
                "date":         d,
                "total":        b["total"],
                "high_risk":    b["high_risk"],
                "avg_risk_score": round(sum(scores)/len(scores), 1) if scores else 0,
            })
        return result
    except Exception as exc:
        logger.debug("[fraud_analytics] get_fraud_trend error: %s", exc)
        return []


def get_quality_trend(days: int = 14) -> List[Dict]:
    """Daily average quality score from fraud_analysis."""
    try:
        sb    = get_supabase()
        from app.analytics.metrics_engine import _days_ago, _now
        from datetime import timedelta
        since = _days_ago(days)
        rows  = (
            sb.table("fraud_analysis")
            .select("analyzed_at, quality_score, is_screenshot, duplicate_detected")
            .gte("analyzed_at", since)
            .execute()
        ).data or []
        bucket: Dict[str, Dict] = {}
        for r in rows:
            day = str(r.get("analyzed_at", ""))[:10]
            b   = bucket.setdefault(day, {"scores": [], "screenshots": 0, "dups": 0})
            b["scores"].append(r.get("quality_score", 0))
            if r.get("is_screenshot"):        b["screenshots"] += 1
            if r.get("duplicate_detected"):   b["dups"]        += 1
        result = []
        for i in range(days - 1, -1, -1):
            d = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
            b = bucket.get(d, {"scores": [], "screenshots": 0, "dups": 0})
            sc = b["scores"]
            result.append({
                "date":             d,
                "avg_quality":      round(sum(sc)/len(sc), 1) if sc else 0,
                "screenshot_count": b["screenshots"],
                "duplicate_count":  b["dups"],
            })
        return result
    except Exception as exc:
        logger.debug("[fraud_analytics] get_quality_trend error: %s", exc)
        return []


def get_fraud_analytics(period: str = "week", trend_days: int = 14) -> Dict:
    """Full fraud analytics bundle."""
    return {
        "summary":          get_fraud_summary_counts(period),
        "risk_distribution":get_risk_distribution(period),
        "top_risky_users":  get_top_risky_users(),
        "fraud_trend":      get_fraud_trend(trend_days),
        "duplicate_trend":  get_duplicate_attack_trend(trend_days),
        "quality_trend":    get_quality_trend(trend_days),
    }
