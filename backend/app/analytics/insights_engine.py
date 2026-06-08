"""
app/analytics/insights_engine.py — AI Insights & recommendations engine
========================================================================
Generates natural-language operational insights from aggregated metrics.

Each insight has:
  type:           category tag
  severity:       INFO | WARNING | CRITICAL
  message:        natural language insight string
  recommendation: actionable next step
  metric:         the supporting numeric data
"""

from __future__ import annotations
from typing import Dict, List, Optional


# ── Insight builder ───────────────────────────────────────────────────────────

def _insight(
    type_:          str,
    severity:       str,
    message:        str,
    recommendation: str,
    metric:         Optional[float] = None,
) -> Dict:
    return {
        "type":           type_,
        "severity":       severity,
        "message":        message,
        "recommendation": recommendation,
        "metric":         metric,
    }


# ── Rule-based insight generators ────────────────────────────────────────────

def _ocr_insights(ocr_data: Dict) -> List[Dict]:
    insights = []
    sr   = ocr_data.get("success_rate", {})
    conf = ocr_data.get("confidence_dist", {})

    failure_rate = sr.get("failure_rate", 0)
    avg_conf     = sr.get("avg_confidence", 0)
    low_conf_band = (conf.get("bands") or {}).get("0-40", 0)
    total         = max(sr.get("total", 1), 1)

    if failure_rate > 15:
        insights.append(_insight(
            "ocr_high_failure",
            "CRITICAL",
            f"OCR failure rate is {failure_rate:.1f}% — above acceptable threshold (15%).",
            "Review image preprocessing settings; consider lowering Tesseract PSM mode or switching primary OCR engine.",
            failure_rate,
        ))
    elif failure_rate > 8:
        insights.append(_insight(
            "ocr_elevated_failure",
            "WARNING",
            f"OCR failure rate is elevated at {failure_rate:.1f}%.",
            "Check for increase in low-quality uploads. Consider stricter document quality gates.",
            failure_rate,
        ))

    if avg_conf < 0.55:
        insights.append(_insight(
            "ocr_low_confidence",
            "WARNING",
            f"Average OCR confidence is {avg_conf:.2%} — document quality may be declining.",
            "Analyse recent uploads for blur, low resolution, or WhatsApp compression artifacts.",
            avg_conf,
        ))

    low_conf_pct = round(low_conf_band / total * 100, 1)
    if low_conf_pct > 20:
        insights.append(_insight(
            "low_confidence_band",
            "WARNING",
            f"{low_conf_pct}% of extractions have confidence below 40%.",
            "Enable mandatory image quality check at upload time to reject unreadable documents.",
            low_conf_pct,
        ))

    doc_types = (ocr_data.get("doc_type_breakdown") or {}).get("rates", {})
    if "unknown" in doc_types and doc_types["unknown"] > 10:
        insights.append(_insight(
            "unknown_doc_type",
            "WARNING",
            f"{doc_types['unknown']:.1f}% of documents could not be identified (unknown type).",
            "Check that uploaded documents are Aadhaar or PAN cards in acceptable image quality.",
            doc_types["unknown"],
        ))

    return insights


def _fraud_insights(fraud_data: Dict) -> List[Dict]:
    insights = []
    summary = fraud_data.get("summary", {})
    dup_trend = fraud_data.get("duplicate_trend", [])

    fraud_rate = summary.get("fraud_rate", 0)
    dup_rate   = summary.get("duplicate_rate", 0)
    critical   = summary.get("critical_count", 0)

    if fraud_rate > 20:
        insights.append(_insight(
            "high_fraud_rate",
            "CRITICAL",
            f"Fraud rate is critically high at {fraud_rate:.1f}% of all processed documents.",
            "Immediately review HIGH_RISK cases; consider temporarily increasing manual verification threshold.",
            fraud_rate,
        ))
    elif fraud_rate > 10:
        insights.append(_insight(
            "elevated_fraud_rate",
            "WARNING",
            f"Fraud rate is {fraud_rate:.1f}% — significantly above baseline.",
            "Investigate top risky users; check for coordinated duplicate identity attacks.",
            fraud_rate,
        ))

    if dup_rate > 5:
        insights.append(_insight(
            "duplicate_attack",
            "CRITICAL" if dup_rate > 15 else "WARNING",
            f"Duplicate identity rate is {dup_rate:.1f}%. Possible coordinated identity fraud.",
            "Cross-reference duplicate matches; block identified offenders and alert compliance team.",
            dup_rate,
        ))

    if critical > 0:
        insights.append(_insight(
            "critical_risk_cases",
            "CRITICAL",
            f"{critical} CRITICAL_RISK cases require immediate human review.",
            "Escalate critical cases to fraud investigation team immediately.",
            float(critical),
        ))

    # Duplicate trend spike detection
    if len(dup_trend) >= 8:
        last3  = sum(d.get("duplicate_count", 0) for d in dup_trend[-3:])
        prev5  = sum(d.get("duplicate_count", 0) for d in dup_trend[-8:-3])
        avg_prev = prev5 / 5 if prev5 > 0 else 0
        if avg_prev > 0 and last3 / 3 > avg_prev * 2:
            insights.append(_insight(
                "duplicate_spike",
                "WARNING",
                "Duplicate Aadhaar/PAN attacks have surged in the last 3 days.",
                "Strengthen ID deduplication checks; flag repeat uploaders for manual investigation.",
                round(last3 / 3, 1),
            ))

    return insights


def _reviewer_insights(reviewer_data: Dict) -> List[Dict]:
    insights = []
    backlog  = reviewer_data.get("queue_backlog", {})
    pending  = backlog.get("total_pending", 0)
    high_p   = backlog.get("high_priority", 0)
    board    = reviewer_data.get("leaderboard", [])

    if pending > 300:
        insights.append(_insight(
            "queue_overloaded",
            "CRITICAL",
            f"Review queue has {pending} pending items — operations are overloaded.",
            "Add more reviewers or increase auto-approval threshold for low-risk cases.",
            float(pending),
        ))
    elif pending > 150:
        insights.append(_insight(
            "queue_elevated",
            "WARNING",
            f"Review queue has {pending} pending reviews — backlog building.",
            "Consider bulk-approving LOW_RISK POSSIBLE_MATCH cases after threshold review.",
            float(pending),
        ))

    if high_p > 30:
        insights.append(_insight(
            "high_priority_backlog",
            "WARNING",
            f"{high_p} HIGH-priority reviews are unprocessed.",
            "Assign senior reviewers to clear high-priority queue immediately.",
            float(high_p),
        ))

    if not board:
        insights.append(_insight(
            "no_reviewer_activity",
            "INFO",
            "No reviewer activity detected in the selected period.",
            "Ensure review team is actively processing the queue.",
            0,
        ))

    corr_freq = reviewer_data.get("correction_frequency", {})
    if (corr_freq.get("total_corrections") or 0) > 50:
        most = corr_freq.get("most_corrected", "name")
        insights.append(_insight(
            "frequent_corrections",
            "INFO",
            f"Reviewers made {corr_freq['total_corrections']} corrections this week. "
            f"Most corrected field: '{most}'.",
            f"Review OCR extraction accuracy for '{most}' field — possible systematic issue.",
            float(corr_freq["total_corrections"]),
        ))

    return insights


def _quality_insights(fraud_data: Dict) -> List[Dict]:
    insights = []
    summary = fraud_data.get("summary", {})
    total   = max(summary.get("total", 1), 1)
    ss_count = summary.get("screenshot_count", 0)
    ss_rate  = round(ss_count / total * 100, 1)

    if ss_rate > 30:
        insights.append(_insight(
            "high_screenshot_rate",
            "WARNING",
            f"{ss_rate:.1f}% of uploads appear to be screenshots rather than camera captures.",
            "Add UI guidance to users: capture original document, not screenshots.",
            ss_rate,
        ))

    quality_trend = fraud_data.get("quality_trend", [])
    if len(quality_trend) >= 7:
        last3 = [d.get("avg_quality", 0) for d in quality_trend[-3:] if d.get("avg_quality")]
        prev4 = [d.get("avg_quality", 0) for d in quality_trend[-7:-3] if d.get("avg_quality")]
        if last3 and prev4:
            recent = sum(last3) / len(last3)
            past   = sum(prev4) / len(prev4)
            if past > 0 and recent < past * 0.85:
                insights.append(_insight(
                    "quality_degradation",
                    "WARNING",
                    f"Average document quality has dropped {((past-recent)/past*100):.1f}% in the last 3 days.",
                    "Check if a specific user cohort or document type is driving quality degradation.",
                    round(recent, 1),
                ))

    return insights


# ── Public API ────────────────────────────────────────────────────────────────

def generate_insights(
    ocr_data:      Dict,
    fraud_data:    Dict,
    reviewer_data: Dict,
) -> Dict:
    """
    Generate all operational insights.

    Returns:
        {
            "insights":       [sorted by severity],
            "top_insight":    str,
            "total":          int,
            "critical":       int,
            "warnings":       int,
            "infos":          int,
            "recommendation": str,
        }
    """
    all_insights: List[Dict] = []
    all_insights.extend(_ocr_insights(ocr_data))
    all_insights.extend(_fraud_insights(fraud_data))
    all_insights.extend(_reviewer_insights(reviewer_data))
    all_insights.extend(_quality_insights(fraud_data))

    # Sort: CRITICAL → WARNING → INFO
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    all_insights.sort(key=lambda x: order.get(x.get("severity", "INFO"), 2))

    critical = sum(1 for i in all_insights if i.get("severity") == "CRITICAL")
    warnings = sum(1 for i in all_insights if i.get("severity") == "WARNING")
    infos    = sum(1 for i in all_insights if i.get("severity") == "INFO")

    top_insight    = all_insights[0]["message"]    if all_insights else "System operating normally."
    recommendation = all_insights[0]["recommendation"] if all_insights else "No action required."

    return {
        "insights":       all_insights,
        "top_insight":    top_insight,
        "total":          len(all_insights),
        "critical":       critical,
        "warnings":       warnings,
        "infos":          infos,
        "recommendation": recommendation,
    }
