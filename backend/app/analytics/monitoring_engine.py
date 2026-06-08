"""
app/analytics/monitoring_engine.py — System health & performance tracking
=========================================================================
Tracks API latency, worker health, DB connectivity, queue performance.
Generates operational alerts stored in the alerts table.
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional
from datetime import datetime, timezone
from app.core.logger import logger
from app.core.supabase_client import get_supabase


# ── DB connectivity check ─────────────────────────────────────────────────────

def check_db_health() -> Dict:
    """Ping Supabase and measure round-trip latency."""
    try:
        start = time.perf_counter()
        sb    = get_supabase()
        sb.table("users").select("id").limit(1).execute()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = "healthy" if latency_ms < 500 else "degraded"
        return {"status": status, "latency_ms": latency_ms}
    except Exception as exc:
        return {"status": "unavailable", "latency_ms": -1, "error": str(exc)}


# ── Worker health ─────────────────────────────────────────────────────────────

def check_worker_health() -> Dict:
    """
    Infer worker health from pending review + recent extraction data.
    If there are documents uploaded >1h ago with no extraction, worker may be stuck.
    """
    try:
        sb = get_supabase()
        from app.analytics.metrics_engine import _now
        from datetime import timedelta
        one_hour_ago = (_now() - timedelta(hours=1)).isoformat()

        # Documents uploaded >1h ago but with no extracted_data
        docs_res = (
            sb.table("documents")
            .select("id", count="exact")
            .lt("uploaded_at", one_hour_ago)
            .execute()
        )
        total_docs = docs_res.count or 0

        extracted_res = (
            sb.table("extracted_data")
            .select("id", count="exact")
            .execute()
        )
        total_extracted = extracted_res.count or 0

        pending_ratio = max(0, total_docs - total_extracted) / max(total_docs, 1)
        status = "healthy"
        if pending_ratio > 0.5:
            status = "degraded"
        elif pending_ratio > 0.8:
            status = "critical"

        return {
            "status":             status,
            "total_documents":    total_docs,
            "total_extracted":    total_extracted,
            "unprocessed_count":  max(0, total_docs - total_extracted),
            "coverage_rate":      round((1 - pending_ratio) * 100, 1),
        }
    except Exception as exc:
        logger.debug("[monitoring] worker_health error: %s", exc)
        return {"status": "unknown", "error": str(exc)}


# ── Queue health ──────────────────────────────────────────────────────────────

def check_queue_health() -> Dict:
    """Review queue depth and priority breakdown."""
    try:
        from app.analytics.reviewer_analytics import get_queue_backlog
        backlog = get_queue_backlog()
        pending = backlog.get("total_pending", 0)
        status  = "healthy"
        if pending > 500:    status = "critical"
        elif pending > 200:  status = "degraded"
        return {"status": status, **backlog}
    except Exception as exc:
        return {"status": "unknown", "error": str(exc)}


# ── Alert system ──────────────────────────────────────────────────────────────

def get_active_alerts(limit: int = 50) -> List[Dict]:
    """Fetch unresolved alerts from DB."""
    try:
        sb  = get_supabase()
        res = (
            sb.table("alerts")
            .select("*")
            .eq("resolved", False)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.debug("[monitoring] get_active_alerts error: %s", exc)
        return []


def create_alert(
    alert_type:   str,
    severity:     str,
    title:        str,
    message:      str,
    metric_name:  Optional[str]  = None,
    metric_value: Optional[float] = None,
    threshold:    Optional[float] = None,
) -> Optional[str]:
    """Create a new alert record. Returns alert ID."""
    payload = {
        "alert_type":   alert_type,
        "severity":     severity,
        "title":        title,
        "message":      message,
        "metric_name":  metric_name,
        "metric_value": metric_value,
        "threshold":    threshold,
        "resolved":     False,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    try:
        sb  = get_supabase()
        res = sb.table("alerts").insert(payload).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.debug("[monitoring] create_alert error: %s", exc)
        return None


def resolve_alert(alert_id: str) -> bool:
    """Mark an alert as resolved."""
    try:
        sb = get_supabase()
        sb.table("alerts").update({
            "resolved": True,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", alert_id).execute()
        return True
    except Exception as exc:
        logger.debug("[monitoring] resolve_alert error: %s", exc)
        return False


def generate_alerts_from_anomalies(anomalies: List[Dict]) -> int:
    """Convert anomaly detections into DB alert records."""
    count = 0
    for a in anomalies:
        sev   = a.get("severity", "INFO")
        atype = a.get("anomaly_type", "unknown")
        aid   = create_alert(
            alert_type   = atype,
            severity     = sev,
            title        = atype.replace("_", " ").title(),
            message      = a.get("message", ""),
            metric_name  = atype,
            metric_value = a.get("today_value"),
            threshold    = a.get("threshold"),
        )
        if aid:
            count += 1
    return count


# ── Record system metric ──────────────────────────────────────────────────────

def record_metric(name: str, value: float, unit: str = "count",
                  tags: Optional[Dict] = None) -> None:
    """Append a point-in-time metric to system_metrics table."""
    try:
        sb = get_supabase()
        sb.table("system_metrics").insert({
            "metric_name":  name,
            "metric_value": round(value, 4),
            "unit":         unit,
            "tags":         tags or {},
            "recorded_at":  datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        logger.debug("[monitoring] record_metric error: %s", exc)


# ── System health summary ─────────────────────────────────────────────────────

def get_system_health() -> Dict:
    """
    Master system health check.

    Returns:
        {
            "system_health":  str (HEALTHY | WARNING | CRITICAL),
            "db":             {...},
            "worker":         {...},
            "queue":          {...},
            "active_alerts":  int,
            "checked_at":     str,
        }
    """
    db_health     = check_db_health()
    worker_health = check_worker_health()
    queue_health  = check_queue_health()
    active_alerts = get_active_alerts(limit=5)

    statuses = [
        db_health.get("status", "unknown"),
        worker_health.get("status", "unknown"),
        queue_health.get("status", "unknown"),
    ]

    if "critical" in statuses or "unavailable" in statuses:
        overall = "CRITICAL"
    elif "degraded" in statuses:
        overall = "WARNING"
    else:
        overall = "HEALTHY"

    return {
        "system_health":   overall,
        "db":              db_health,
        "worker":          worker_health,
        "queue":           queue_health,
        "active_alerts":   len(active_alerts),
        "latest_alerts":   active_alerts[:3],
        "checked_at":      datetime.now(timezone.utc).isoformat(),
    }
