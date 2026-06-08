"""
app/fraud/risk_scorer.py — Master enterprise risk scoring engine
===============================================================
calculate_risk_score() combines all fraud signals into a single
risk score (0-100) and maps it to a risk level.

WEIGHTS (sum to 1.0):
  tamper_score:      0.30  — most critical (document was modified)
  duplicate_score:   0.25  — identity collision (reused document)
  quality_score:     0.20  — inversed (low quality = higher risk)
  metadata_score:    0.15  — software/screenshot traces
  pattern_score:     0.10  — behavioural signals

RISK LEVELS:
  0-24   → LOW_RISK
  25-49  → MEDIUM_RISK
  50-74  → HIGH_RISK
  75-100 → CRITICAL_RISK
"""

from __future__ import annotations
from typing import Dict
from app.core.logger import logger


# ── Risk thresholds ───────────────────────────────────────────────────────────

class RiskLevel:
    LOW      = "LOW_RISK"
    MEDIUM   = "MEDIUM_RISK"
    HIGH     = "HIGH_RISK"
    CRITICAL = "CRITICAL_RISK"


RISK_THRESHOLDS = {
    RiskLevel.LOW:      (0,  24),
    RiskLevel.MEDIUM:   (25, 49),
    RiskLevel.HIGH:     (50, 74),
    RiskLevel.CRITICAL: (75, 100),
}

# Component weights — must sum to 1.0
WEIGHTS = {
    "tamper":    0.30,
    "duplicate": 0.25,
    "quality":   0.20,
    "metadata":  0.15,
    "pattern":   0.10,
}


# ── Recommendation map ────────────────────────────────────────────────────────

def _recommend(risk_level: str, tamper_score: int, duplicate_score: int) -> str:
    if risk_level == RiskLevel.CRITICAL:
        if duplicate_score >= 70:
            return "block_and_investigate_identity_collision"
        if tamper_score >= 70:
            return "block_and_flag_for_fraud_review"
        return "escalate_to_fraud_team"
    if risk_level == RiskLevel.HIGH:
        return "manual_review_required"
    if risk_level == RiskLevel.MEDIUM:
        return "enhanced_verification_recommended"
    return "proceed_with_standard_review"


# ── Public API ────────────────────────────────────────────────────────────────

def calculate_risk_score(
    tamper_score:    int,
    duplicate_score: int,
    quality_score:   int,
    metadata_score:  int,
    pattern_score:   int,
    ocr_confidence:  float = 1.0,
) -> Dict:
    """
    Master risk score calculator.

    Args:
        tamper_score:    0-100 (from tamper_detector)
        duplicate_score: 0-100 (from duplicate_detector)
        quality_score:   0-100 (INVERTED — low quality = high risk)
        metadata_score:  0-100 (from metadata_analyzer)
        pattern_score:   0-100 (from suspicious_patterns)
        ocr_confidence:  0-1.0 (from OCR pipeline, used as penalty modifier)

    Returns:
        {
            "risk_score":       int (0-100),
            "risk_level":       str,
            "recommendation":   str,
            "component_scores": {tamper, duplicate, quality, metadata, pattern},
            "weights_used":     dict,
            "ocr_penalty":      float,
        }
    """
    # Invert quality score (low quality → high risk contribution)
    inverted_quality = 100 - max(0, min(100, quality_score))

    components = {
        "tamper":    max(0, min(100, tamper_score)),
        "duplicate": max(0, min(100, duplicate_score)),
        "quality":   inverted_quality,
        "metadata":  max(0, min(100, metadata_score)),
        "pattern":   max(0, min(100, pattern_score)),
    }

    # Weighted sum
    raw_score = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)

    # OCR confidence penalty: very low OCR confidence adds risk (document unreadable)
    ocr_penalty = 0.0
    if ocr_confidence < 0.40:
        ocr_penalty = (0.40 - ocr_confidence) * 30   # up to +12 points
    elif ocr_confidence < 0.70:
        ocr_penalty = (0.70 - ocr_confidence) * 10   # up to +3 points

    final_score = min(100, int(raw_score + ocr_penalty))

    # Determine risk level
    risk_level = RiskLevel.LOW
    for level, (lo, hi) in RISK_THRESHOLDS.items():
        if lo <= final_score <= hi:
            risk_level = level
            break

    recommendation = _recommend(risk_level, tamper_score, duplicate_score)

    logger.info(
        "[risk_scorer] risk_score=%d level=%s components=%s ocr_penalty=%.1f",
        final_score, risk_level, components, ocr_penalty
    )

    return {
        "risk_score":       final_score,
        "risk_level":       risk_level,
        "recommendation":   recommendation,
        "component_scores": components,
        "weights_used":     WEIGHTS,
        "ocr_penalty":      round(ocr_penalty, 2),
    }


def map_risk_to_review_priority(risk_level: str) -> int:
    """Map fraud risk level to review queue priority (1=HIGH, 2=MEDIUM, 3=LOW)."""
    return {
        RiskLevel.CRITICAL: 1,
        RiskLevel.HIGH:     1,
        RiskLevel.MEDIUM:   2,
        RiskLevel.LOW:      3,
    }.get(risk_level, 2)
