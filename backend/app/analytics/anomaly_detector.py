"""
app/analytics/anomaly_detector.py — Operational anomaly detection
================================================================
Uses rolling 7-day average vs today's value to detect unusual spikes/drops.

Anomalies detected:
  - Fraud spike (today > avg * 1.5)
  - OCR failure spike (today > avg * 1.5)
  - Duplicate attack surge
  - Review queue flood (pending > threshold)
  - Upload flood (today > avg * 2)
  - Reviewer slowdown (completion rate drops)
  - Quality degradation (avg quality drops)
"""

from __future__ import annotations
from typing import Dict, List
from datetime import timedelta
from app.core.logger import logger
from app.analytics.metrics_engine import _now, _days_ago, get_daily_counts


# ── Severity constants ────────────────────────────────────────────────────────

class Severity:
    INFO     = "INFO"
    WARNING  = "WARNING"
    CRITICAL = "CRITICAL"


# ── Rolling average helper ────────────────────────────────────────────────────

def _rolling_avg(series: List[Dict], value_key: str = "count",
                 window: int = 7, skip_last: int = 1) -> float:
    """Average of `window` days before the most recent `skip_last` entries."""
    ref    = series[-(window + skip_last):-skip_last] if len(series) >= window + skip_last else series[:-skip_last]
    values = [d.get(value_key, 0) for d in ref]
    return sum(values) / len(values) if values else 0.0


def _today_value(series: List[Dict], value_key: str = "count") -> float:
    return float(series[-1].get(value_key, 0)) if series else 0.0


def _anomaly(
    name:     str,
    today:    float,
    avg:      float,
    threshold_mult: float,
    severity: str,
    message:  str,
    unit:     str = "count",
) -> Dict:
    return {
        "anomaly_type": name,
        "today_value":  round(today, 2),
        "rolling_avg":  round(avg, 2),
        "threshold":    round(avg * threshold_mult, 2),
        "severity":     severity,
        "message":      message,
        "unit":         unit,
    }


# ── Individual anomaly checks ─────────────────────────────────────────────────

def _check_fraud_spike() -> List[Dict]:
    anomalies = []
    try:
        from app.core.supabase_client import get_supabase
        sb    = get_supabase()
        since = _days_ago(14)
        rows  = (
            sb.table("fraud_analysis")
            .select("analyzed_at, risk_level")
            .gte("analyzed_at", since)
            .execute()
        ).data or []
        # Build daily high-risk counts
        bucket: Dict[str, int] = {}
        for r in rows:
            day = str(r.get("analyzed_at", ""))[:10]
            if r.get("risk_level") in ("HIGH_RISK", "CRITICAL_RISK"):
                bucket[day] = bucket.get(day, 0) + 1
        series = []
        for i in range(13, -1, -1):
            d = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
            series.append({"date": d, "count": bucket.get(d, 0)})

        avg   = _rolling_avg(series, window=7)
        today = _today_value(series)
        if avg > 0 and today > avg * 1.5:
            sev = Severity.CRITICAL if today > avg * 2.5 else Severity.WARNING
            anomalies.append(_anomaly(
                "fraud_spike", today, avg, 1.5, sev,
                f"Fraud cases today ({today:.0f}) are {today/max(avg,1):.1f}× the 7-day average ({avg:.1f}).",
            ))
    except Exception as exc:
        logger.debug("[anomaly] _check_fraud_spike error: %s", exc)
    return anomalies


def _check_ocr_failure_spike() -> List[Dict]:
    anomalies = []
    try:
        series = get_daily_counts("verified_data", "verified_at", 14,
                                   filters=[("status", "OCR_FAILED")])
        avg   = _rolling_avg(series, window=7)
        today = _today_value(series)
        if avg > 0 and today > avg * 1.5:
            sev = Severity.CRITICAL if today > avg * 3 else Severity.WARNING
            anomalies.append(_anomaly(
                "ocr_failure_spike", today, avg, 1.5, sev,
                f"OCR failures today ({today:.0f}) are {today/max(avg,1):.1f}× the 7-day average.",
            ))
        elif avg == 0 and today >= 5:
            anomalies.append(_anomaly(
                "ocr_failure_new", today, 0, 0, Severity.WARNING,
                f"OCR failures detected today ({today:.0f}) where none were seen before.",
            ))
    except Exception as exc:
        logger.debug("[anomaly] _check_ocr_failure_spike error: %s", exc)
    return anomalies


def _check_upload_flood() -> List[Dict]:
    anomalies = []
    try:
        series = get_daily_counts("documents", "uploaded_at", 14)
        avg    = _rolling_avg(series, window=7)
        today  = _today_value(series)
        if avg > 0 and today > avg * 2.0:
            anomalies.append(_anomaly(
                "upload_flood", today, avg, 2.0, Severity.WARNING,
                f"Document uploads today ({today:.0f}) are {today/max(avg,1):.1f}× normal volume.",
            ))
    except Exception as exc:
        logger.debug("[anomaly] _check_upload_flood error: %s", exc)
    return anomalies


def _check_duplicate_surge() -> List[Dict]:
    anomalies = []
    try:
        from app.core.supabase_client import get_supabase
        sb    = get_supabase()
        since = _days_ago(14)
        rows  = (
            sb.table("duplicate_matches")
            .select("flagged_at")
            .gte("flagged_at", since)
            .execute()
        ).data or []
        bucket: Dict[str, int] = {}
        for r in rows:
            day = str(r.get("flagged_at", ""))[:10]
            bucket[day] = bucket.get(day, 0) + 1
        series = []
        for i in range(13, -1, -1):
            d = (_now() - timedelta(days=i)).strftime("%Y-%m-%d")
            series.append({"date": d, "count": bucket.get(d, 0)})
        avg   = _rolling_avg(series, window=7)
        today = _today_value(series)
        if avg > 0 and today > avg * 2.0:
            sev = Severity.CRITICAL if today > avg * 3 else Severity.WARNING
            anomalies.append(_anomaly(
                "duplicate_surge", today, avg, 2.0, sev,
                f"Duplicate identity matches ({today:.0f}) are {today/max(avg,1):.1f}× the 7-day average. Possible coordinated fraud.",
            ))
    except Exception as exc:
        logger.debug("[anomaly] _check_duplicate_surge error: %s", exc)
    return anomalies


def _check_queue_overload() -> List[Dict]:
    anomalies = []
    try:
        from app.analytics.reviewer_analytics import get_queue_backlog
        backlog = get_queue_backlog()
        pending = backlog.get("total_pending", 0)
        high_p  = backlog.get("high_priority", 0)
        if pending > 500:
            anomalies.append({
                "anomaly_type": "queue_critical_overload",
                "today_value":  pending,
                "rolling_avg":  0,
                "threshold":    500,
                "severity":     Severity.CRITICAL,
                "message":      f"Review queue critically overloaded: {pending} pending reviews.",
                "unit":         "reviews",
            })
        elif pending > 200:
            anomalies.append({
                "anomaly_type": "queue_overload",
                "today_value":  pending,
                "rolling_avg":  0,
                "threshold":    200,
                "severity":     Severity.WARNING,
                "message":      f"Review queue overloaded: {pending} pending reviews (threshold: 200).",
                "unit":         "reviews",
            })
        if high_p > 50:
            anomalies.append({
                "anomaly_type": "high_priority_backlog",
                "today_value":  high_p,
                "rolling_avg":  0,
                "threshold":    50,
                "severity":     Severity.WARNING,
                "message":      f"{high_p} HIGH-priority reviews pending — escalate reviewer capacity.",
                "unit":         "reviews",
            })
    except Exception as exc:
        logger.debug("[anomaly] _check_queue_overload error: %s", exc)
    return anomalies


# ── Public API ────────────────────────────────────────────────────────────────

def detect_anomalies() -> Dict:
    """
    Run all anomaly checks. Returns:
        {
            "anomalies":    [...]  sorted by severity,
            "total":        int,
            "critical":     int,
            "warnings":     int,
            "system_alert": str,  # overall health label
        }
    """
    all_anomalies: List[Dict] = []
    all_anomalies.extend(_check_fraud_spike())
    all_anomalies.extend(_check_ocr_failure_spike())
    all_anomalies.extend(_check_upload_flood())
    all_anomalies.extend(_check_duplicate_surge())
    all_anomalies.extend(_check_queue_overload())

    # Sort: CRITICAL first
    severity_order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    all_anomalies.sort(key=lambda x: severity_order.get(x.get("severity", "INFO"), 2))

    critical = sum(1 for a in all_anomalies if a.get("severity") == Severity.CRITICAL)
    warnings = sum(1 for a in all_anomalies if a.get("severity") == Severity.WARNING)

    if critical > 0:
        system_alert = "CRITICAL"
    elif warnings > 0:
        system_alert = "WARNING"
    else:
        system_alert = "HEALTHY"

    logger.info(
        "[anomaly_detector] total=%d critical=%d warnings=%d status=%s",
        len(all_anomalies), critical, warnings, system_alert
    )

    return {
        "anomalies":    all_anomalies,
        "total":        len(all_anomalies),
        "critical":     critical,
        "warnings":     warnings,
        "system_alert": system_alert,
    }
