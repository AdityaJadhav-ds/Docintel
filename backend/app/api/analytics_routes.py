"""
app/api/analytics_routes.py — Analytics & monitoring REST endpoints
===================================================================
"""

from __future__ import annotations
import csv
import io
import json
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from app.analytics.dashboard_engine   import get_dashboard_metrics
from app.analytics.ocr_analytics      import get_ocr_analytics
from app.analytics.fraud_analytics    import get_fraud_analytics
from app.analytics.reviewer_analytics import get_reviewer_analytics, get_reviewer_stats
from app.analytics.trend_analyzer     import get_all_trends, get_upload_trend
from app.analytics.anomaly_detector   import detect_anomalies
from app.analytics.insights_engine    import generate_insights
from app.analytics.monitoring_engine  import (
    get_system_health, get_active_alerts, resolve_alert,
    generate_alerts_from_anomalies,
)
from app.schemas.analytics_schema import AlertResolveRequest

router = APIRouter(prefix="/analytics", tags=["Analytics"])


# ── Master dashboard ──────────────────────────────────────────────────────────

@router.get("/dashboard")
def dashboard(
    period:     str = Query("week", description="today|week|month|all"),
    trend_days: int = Query(14, ge=7, le=90),
):
    """
    Complete executive dashboard payload.
    Returns all KPIs, analytics, trends, insights, and system health.
    """
    return get_dashboard_metrics(period=period, trend_days=trend_days)


# ── OCR analytics ─────────────────────────────────────────────────────────────

@router.get("/ocr")
def ocr_analytics(
    period:     str = Query("week"),
    trend_days: int = Query(14, ge=7, le=90),
):
    """OCR performance: success rate, confidence distribution, doc-type breakdown, failure trend."""
    return get_ocr_analytics(period=period, trend_days=trend_days)


# ── Fraud analytics ───────────────────────────────────────────────────────────

@router.get("/fraud")
def fraud_analytics(
    period:     str = Query("week"),
    trend_days: int = Query(14, ge=7, le=90),
):
    """Fraud intelligence: risk distribution, top risky users, fraud/duplicate/quality trends."""
    return get_fraud_analytics(period=period, trend_days=trend_days)


# ── Reviewer analytics ────────────────────────────────────────────────────────

@router.get("/reviewers")
def reviewer_analytics(period: str = Query("week")):
    """Reviewer productivity: leaderboard, queue backlog, correction frequency."""
    return get_reviewer_analytics(period=period)


@router.get("/reviewers/{reviewer_id}")
def single_reviewer(reviewer_id: str, period: str = Query("week")):
    """Stats for a specific reviewer."""
    stats = get_reviewer_stats(reviewer_id=reviewer_id, period=period)
    if not stats:
        raise HTTPException(404, f"No data for reviewer '{reviewer_id}'.")
    return {"reviewer_id": reviewer_id, "period": period, "stats": stats[0]}


# ── Trends ────────────────────────────────────────────────────────────────────

@router.get("/trends")
def trends(
    period: str = Query("daily"),
    days:   int = Query(30, ge=7, le=365),
):
    """All trend time series: uploads, reviews, fraud rate, OCR confidence."""
    return get_all_trends(days=days)


@router.get("/trends/uploads")
def upload_trends(
    period: str = Query("daily"),
    days:   int = Query(30, ge=7, le=90),
):
    """Document upload volume trend with WoW growth rate."""
    return get_upload_trend(period=period, days=days)


# ── Anomaly detection ─────────────────────────────────────────────────────────

@router.get("/anomalies")
def anomalies():
    """
    Detect operational anomalies using rolling-average comparison.
    Creates alert records for critical anomalies.
    """
    result = detect_anomalies()
    # Persist critical anomalies as alerts
    if result.get("critical", 0) > 0:
        critical_anomalies = [a for a in result["anomalies"] if a.get("severity") == "CRITICAL"]
        generate_alerts_from_anomalies(critical_anomalies)
    return result


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
def list_alerts(limit: int = Query(50, le=200)):
    """All unresolved operational alerts."""
    alerts = get_active_alerts(limit=limit)
    return {"alerts": alerts, "total": len(alerts)}


@router.post("/alerts/resolve")
def resolve(body: AlertResolveRequest):
    """Mark an alert as resolved."""
    success = resolve_alert(body.alert_id)
    if not success:
        raise HTTPException(400, "Could not resolve alert.")
    return {"success": True, "alert_id": body.alert_id}


# ── System health ─────────────────────────────────────────────────────────────

@router.get("/system-health")
def system_health():
    """DB latency, worker coverage, queue depth, active alert count."""
    return get_system_health()


# ── AI insights ───────────────────────────────────────────────────────────────

@router.get("/insights")
def insights(period: str = Query("week"), trend_days: int = Query(14)):
    """AI-generated operational insights with recommendations."""
    from app.analytics.ocr_analytics    import get_ocr_analytics
    from app.analytics.fraud_analytics  import get_fraud_analytics
    from app.analytics.reviewer_analytics import get_reviewer_analytics
    ocr_data      = get_ocr_analytics(period, trend_days)
    fraud_data    = get_fraud_analytics(period, trend_days)
    reviewer_data = get_reviewer_analytics(period)
    return generate_insights(ocr_data, fraud_data, reviewer_data)


# ── Exports ───────────────────────────────────────────────────────────────────

@router.get("/export/dashboard/json")
def export_dashboard_json(period: str = Query("week")):
    """Export full dashboard metrics as JSON."""
    data = get_dashboard_metrics(period=period)
    return JSONResponse(content=data)


@router.get("/export/fraud/csv")
def export_fraud_csv(period: str = Query("week")):
    """Export fraud summary as CSV."""
    fraud = get_fraud_analytics(period=period)
    summary = fraud.get("summary", {})
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(["Metric", "Value"])
    for k, v in summary.items():
        if not isinstance(v, dict):
            writer.writerow([k, v])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fraud_report.csv"},
    )


@router.get("/export/reviewers/csv")
def export_reviewers_csv(period: str = Query("week")):
    """Export reviewer leaderboard as CSV."""
    data        = get_reviewer_analytics(period)
    leaderboard = data.get("leaderboard", [])
    output      = io.StringIO()
    if leaderboard:
        writer = csv.DictWriter(output, fieldnames=leaderboard[0].keys(), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leaderboard)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reviewer_report.csv"},
    )
