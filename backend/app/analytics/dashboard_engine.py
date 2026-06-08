"""
app/analytics/dashboard_engine.py — Master executive dashboard aggregator
=========================================================================
get_dashboard_metrics() is the single call for the front-end dashboard.
Assembles all sub-engine results into the required output format.
"""

from __future__ import annotations
from typing import Dict
from app.core.logger import logger
from app.analytics.metrics_engine import (
    count_users, count_documents, get_verification_stats,
    get_review_queue_counts, get_fraud_summary_counts, get_avg_ocr_confidence,
)
from app.analytics.ocr_analytics     import get_ocr_success_rate
from app.analytics.fraud_analytics   import get_risk_distribution
from app.analytics.reviewer_analytics import get_queue_backlog
from app.analytics.trend_analyzer    import get_upload_trend
from app.analytics.anomaly_detector  import detect_anomalies
from app.analytics.insights_engine   import generate_insights
from app.analytics.monitoring_engine import get_system_health

import time as _time

# ── Simple 30-second TTL cache for the dashboard ─────────────────────────────
# The dashboard runs 16+ parallel Supabase queries. Caching the result for 30s
# makes the frontend feel instant without serving significantly stale data.
_DASHBOARD_CACHE: dict = {}   # key: (period, trend_days) → {result, ts}
_DASHBOARD_TTL   = 30         # seconds


def get_dashboard_metrics(period: str = "week", trend_days: int = 14) -> Dict:
    """
    Master dashboard payload.

    Produces the required output format:
        {
          "system_health":     str,
          "ocr_success_rate":  float,
          "fraud_rate":        float,
          "review_queue_size": int,
          "high_risk_cases":   int,
          "top_insight":       str,
          "recommendation":    str,
          ...full detail sections...
        }
    """
    logger.info("[dashboard_engine] Building dashboard metrics (period=%s)", period)

    # ── Cache check ───────────────────────────────────────────────────────────
    cache_key = (period, trend_days)
    cached = _DASHBOARD_CACHE.get(cache_key)
    if cached and (_time.monotonic() - cached["ts"]) < _DASHBOARD_TTL:
        logger.info("[dashboard_engine] Returning cached dashboard (age=%.1fs)",
                    _time.monotonic() - cached["ts"])
        return cached["result"]

    # ── Parallel Execution ───────────────────────────────────────────────────
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        f_total_users      = executor.submit(count_users)
        f_total_docs       = executor.submit(count_documents)
        f_docs_today       = executor.submit(count_documents, period="today")
        f_docs_this_week   = executor.submit(count_documents, period="week")
        f_verif_stats      = executor.submit(get_verification_stats, period)
        f_ocr_rate         = executor.submit(get_ocr_success_rate, period)
        f_queue_counts     = executor.submit(get_review_queue_counts)
        f_queue_backlog    = executor.submit(get_queue_backlog)
        f_fraud_summary    = executor.submit(get_fraud_summary_counts, period)
        f_risk_dist        = executor.submit(get_risk_distribution, period)
        f_upload_trend     = executor.submit(get_upload_trend, days=trend_days)
        f_anomaly_result   = executor.submit(detect_anomalies)
        f_sys_health       = executor.submit(get_system_health)
        
        from app.analytics.ocr_analytics    import get_ocr_analytics
        from app.analytics.fraud_analytics  import get_fraud_analytics
        from app.analytics.reviewer_analytics import get_reviewer_analytics
        
        f_ocr_full      = executor.submit(get_ocr_analytics, period, trend_days)
        f_fraud_full    = executor.submit(get_fraud_analytics, period, trend_days)
        f_reviewer_full = executor.submit(get_reviewer_analytics, period)
        f_avg_ocr_conf  = executor.submit(get_avg_ocr_confidence, period)

        total_users      = f_total_users.result()
        total_docs       = f_total_docs.result()
        docs_today       = f_docs_today.result()
        docs_this_week   = f_docs_this_week.result()
        verif_stats      = f_verif_stats.result()
        ocr_rate         = f_ocr_rate.result()
        queue_counts     = f_queue_counts.result()
        queue_backlog    = f_queue_backlog.result()
        fraud_summary    = f_fraud_summary.result()
        risk_dist        = f_risk_dist.result()
        upload_trend     = f_upload_trend.result()
        anomaly_result   = f_anomaly_result.result()
        sys_health       = f_sys_health.result()
        ocr_full         = f_ocr_full.result()
        fraud_full       = f_fraud_full.result()
        reviewer_full    = f_reviewer_full.result()
        avg_ocr_conf     = f_avg_ocr_conf.result()

    # ── AI insights ───────────────────────────────────────────────────────────
    insights = generate_insights(
        ocr_data      = ocr_full,
        fraud_data    = fraud_full,
        reviewer_data = reviewer_full,
    )

    # ── KPI summary ───────────────────────────────────────────────────────────
    review_queue_size = queue_backlog.get("total_pending", 0)
    high_risk_cases   = fraud_summary.get("high_risk_count", 0)
    fraud_rate        = fraud_summary.get("fraud_rate", 0.0)
    ocr_success_rate  = ocr_rate.get("success_rate", 0.0)

    # Overall system status
    system_health = anomaly_result.get("system_alert", sys_health.get("system_health", "HEALTHY"))

    logger.info(
        "[dashboard_engine] health=%s ocr=%.1f%% fraud=%.1f%% queue=%d insights=%d",
        system_health, ocr_success_rate, fraud_rate, review_queue_size, insights["total"]
    )

    return {
        # ── Required summary format ──
        "system_health":     system_health,
        "ocr_success_rate":  ocr_success_rate,
        "fraud_rate":        fraud_rate,
        "review_queue_size": review_queue_size,
        "high_risk_cases":   high_risk_cases,
        "top_insight":       insights["top_insight"],
        "recommendation":    insights["recommendation"],

        # ── KPI cards ──
        "kpis": {
            "total_users":         total_users,
            "total_documents":     total_docs,
            "documents_today":     docs_today,
            "documents_this_week": docs_this_week,
            "ocr_success_rate":    ocr_success_rate,
            "avg_ocr_confidence":  avg_ocr_conf,
            "review_queue_size":   review_queue_size,
            "auto_approved":       queue_counts.get("auto_approved", 0),
            "auto_rejected":       queue_counts.get("auto_rejected", 0),
            "fraud_rate":          fraud_rate,
            "duplicate_rate":      fraud_summary.get("duplicate_rate", 0.0),
            "high_risk_cases":     high_risk_cases,
        },

        # ── Detail sections ──
        "validation":   verif_stats,
        "ocr":          ocr_full,
        "fraud":        fraud_full,
        "reviewers":    reviewer_full,
        "trends":       upload_trend,
        "anomalies":    anomaly_result,
        "insights":     insights,
        "system":       sys_health,

        "period":       period,
        "trend_days":   trend_days,
    }

    # Store in cache
    _DASHBOARD_CACHE[cache_key] = {"result": result, "ts": _time.monotonic()}
    return result
