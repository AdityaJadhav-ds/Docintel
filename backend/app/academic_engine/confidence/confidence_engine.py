"""
academic_engine/confidence/confidence_engine.py
=================================================
Field-Level Confidence Scoring Engine

Scores each extracted field individually based on:
  - OCR engine confidence
  - Anchor proximity (how close the value was to its expected anchor)
  - Validation pass/fail
  - Pattern match quality (exact regex vs fuzzy)

Overall confidence = weighted average of field-level scores.

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FIELD WEIGHTS (how critical each field is to document understanding)
# ─────────────────────────────────────────────────────────────────────────────

_FIELD_WEIGHTS = {
    "candidate_name":    0.30,
    "board_university":  0.15,
    "passing_year":      0.15,
    "percentage":        0.20,
    "cgpa":              0.20,
    "grade_class":       0.10,
    "result":            0.10,
}

# Minimum field count to consider confidence meaningful
_MIN_FIELDS_FOR_CONFIDENCE = 2


# ─────────────────────────────────────────────────────────────────────────────
# PER-FIELD CONFIDENCE SCORES
# ─────────────────────────────────────────────────────────────────────────────

def _score_candidate_name(value: Optional[str]) -> float:
    """Score based on name quality: word count, length, title case."""
    if not value:
        return 0.0
    words = value.split()
    score = 0.5  # Base for valid name
    if len(words) >= 3:
        score += 0.2
    elif len(words) == 2:
        score += 0.1
    if value == value.title():
        score += 0.15  # Proper title case
    if 10 <= len(value) <= 50:
        score += 0.15
    return min(score, 1.0)


def _score_percentage(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        v = float(value)
        if 35.0 <= v <= 100.0:
            return 0.95  # Common realistic range
        if 10.0 <= v <= 35.0:
            return 0.75  # Unusual but possible
        return 0.5
    except ValueError:
        return 0.0


def _score_cgpa(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        v = float(value)
        if 5.0 <= v <= 10.0:
            return 0.95
        if 0.0 <= v < 5.0:
            return 0.75
        return 0.5
    except ValueError:
        return 0.0


def _score_year(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        yr = int(value)
        if 2000 <= yr <= 2030:
            return 1.0   # Most likely range
        if 1980 <= yr < 2000:
            return 0.85
        return 0.6
    except ValueError:
        return 0.0


def _score_generic(value: Optional[str]) -> float:
    if not value:
        return 0.0
    if len(value.strip()) > 2:
        return 0.85
    return 0.5


_FIELD_SCORERS = {
    "candidate_name":   _score_candidate_name,
    "board_university": _score_generic,
    "passing_year":     _score_year,
    "percentage":       _score_percentage,
    "cgpa":             _score_cgpa,
    "grade_class":      _score_generic,
    "result":           _score_generic,
}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CONFIDENCE ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def compute_field_confidence(field: str, value: Any) -> float:
    """
    Compute confidence score for a single field.

    Args:
        field: Field name string.
        value: Extracted (validated) value.

    Returns:
        Float in [0.0, 1.0].
    """
    scorer = _FIELD_SCORERS.get(field, _score_generic)
    return round(scorer(value), 3)


def compute_overall_confidence(
    extracted: Dict[str, Any],
    ocr_confidence: float = 0.5,
) -> Dict[str, Any]:
    """
    Compute per-field and overall confidence for an extraction result.

    Args:
        extracted:      Validated extracted fields dict.
        ocr_confidence: Average OCR engine confidence (0–1).

    Returns:
        {
          "overall": float,
          "field_scores": {field: score},
          "ocr_contribution": float,
          "field_contribution": float,
          "grade": "high" | "medium" | "low" | "insufficient",
        }
    """
    field_scores: Dict[str, float] = {}
    weighted_sum = 0.0
    weight_total = 0.0

    for field, weight in _FIELD_WEIGHTS.items():
        value = extracted.get(field)
        if value is not None:
            score = compute_field_confidence(field, value)
            field_scores[field] = score
            weighted_sum += score * weight
            weight_total += weight
        # Missing fields contribute 0 but also 0 weight — we normalise

    if weight_total == 0:
        field_contribution = 0.0
    else:
        # Normalise by actual weight present
        field_contribution = weighted_sum / weight_total

    # Blend with OCR confidence (70% field quality, 30% OCR engine)
    overall = round(
        field_contribution * 0.70 + min(ocr_confidence, 1.0) * 0.30,
        3,
    )

    # Grade
    if overall >= 0.70:
        grade = "high"
    elif overall >= 0.45:
        grade = "medium"
    elif overall >= 0.20:
        grade = "low"
    else:
        grade = "insufficient"

    # Coverage: fraction of expected fields found
    found_fields = len([k for k in _FIELD_WEIGHTS if extracted.get(k) is not None])
    coverage = round(found_fields / len(_FIELD_WEIGHTS), 2)

    logger.info(
        "[confidence] overall=%.3f grade=%s coverage=%d/%d ocr=%.2f",
        overall, grade, found_fields, len(_FIELD_WEIGHTS), ocr_confidence,
    )

    return {
        "overall":            overall,
        "field_scores":       field_scores,
        "ocr_contribution":   round(min(ocr_confidence, 1.0) * 0.30, 3),
        "field_contribution": round(field_contribution * 0.70, 3),
        "grade":              grade,
        "fields_found":       found_fields,
        "fields_expected":    len(_FIELD_WEIGHTS),
        "coverage":           coverage,
    }
