"""
academic_engine/validators/academic_validators.py
===================================================
Validation Engine for Extracted Academic Fields

Rules:
  candidate_name  → Alphabets + spaces only, 2+ words, len 5–70
  board_university → Non-empty string, len 3–120
  passing_year    → Integer 1900–2035
  percentage      → Float 0.0–100.0 (only for marksheets)
  cgpa            → Float 0.0–10.0
  grade_class     → Whitelisted string values
  result          → Whitelisted: PASS | FAIL | DISTINCTION | FIRST CLASS | SECOND CLASS

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import re
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ALLOWED RESULT VALUES
# ─────────────────────────────────────────────────────────────────────────────

ALLOWED_RESULTS = {
    "PASS", "FAIL", "DISTINCTION",
    "FIRST CLASS", "SECOND CLASS", "THIRD CLASS", "PASS CLASS",
    "ATKT", "WITHHELD",
}

ALLOWED_GRADES = {
    "Distinction", "First Class with Distinction",
    "First Class", "Second Class", "Third Class", "Pass Class",
    "Outstanding", "Excellent",
    "A+ Grade", "A Grade", "B+ Grade", "B Grade", "C Grade", "D Grade",
    "O / A+", "O Grade",
}


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATORS
# ─────────────────────────────────────────────────────────────────────────────

def validate_candidate_name(value: Any) -> Tuple[bool, Optional[str]]:
    """
    Returns (is_valid, cleaned_value_or_None).
    Rule: alphabets + spaces + hyphens only, 2+ words, len 5–70.
    """
    if not value or not isinstance(value, str):
        return False, None

    s = value.strip()
    if len(s) < 5 or len(s) > 70:
        logger.debug("[validator] Name '%s' failed length check", s)
        return False, None

    # Must have at least 2 words
    words = s.split()
    if len(words) < 2:
        logger.debug("[validator] Name '%s' has < 2 words", s)
        return False, None

    # Allow only alpha, space, hyphen, period (for initials like S.K. Sharma)
    if not re.match(r"^[A-Za-z\s\.\-]+$", s):
        logger.debug("[validator] Name '%s' contains invalid characters", s)
        return False, None

    # Must not contain digits
    if re.search(r"\d", s):
        return False, None

    return True, s


def validate_board_university(value: Any) -> Tuple[bool, Optional[str]]:
    if not value or not isinstance(value, str):
        return False, None
    s = value.strip()
    if len(s) < 3 or len(s) > 120:
        return False, None
    return True, s


def validate_passing_year(value: Any) -> Tuple[bool, Optional[str]]:
    """
    Accepts int, str like '2022', returns normalized 4-digit string or None.
    Range: 1900–2035.
    """
    if value is None:
        return False, None
    try:
        yr = int(str(value).strip())
        if 1900 <= yr <= 2035:
            return True, str(yr)
        return False, None
    except (ValueError, TypeError):
        return False, None


def validate_percentage(value: Any) -> Tuple[bool, Optional[str]]:
    """
    Range: 0.0–100.0.
    Returns string with 2 decimal places.
    """
    if value is None:
        return False, None
    try:
        v = float(str(value).replace("%", "").strip())
        if 0.0 <= v <= 100.0:
            return True, f"{v:.2f}"
        return False, None
    except (ValueError, TypeError):
        return False, None


def validate_cgpa(value: Any) -> Tuple[bool, Optional[str]]:
    """
    Range: 0.0–10.0.
    Returns string with 2 decimal places.
    """
    if value is None:
        return False, None
    try:
        v = float(str(value).strip())
        if 0.0 <= v <= 10.0:
            return True, f"{v:.2f}"
        return False, None
    except (ValueError, TypeError):
        return False, None


def validate_grade_class(value: Any) -> Tuple[bool, Optional[str]]:
    if not value or not isinstance(value, str):
        return False, None
    s = value.strip()
    # Accept any reasonable grade string (normalised by extractor)
    if len(s) < 1 or len(s) > 50:
        return False, None
    # Must be mostly alpha
    alpha = sum(c.isalpha() or c in " +/-" for c in s)
    if alpha / len(s) < 0.7:
        return False, None
    return True, s


def validate_result(value: Any) -> Tuple[bool, Optional[str]]:
    if not value or not isinstance(value, str):
        return False, None
    s = value.strip().upper()
    if s in ALLOWED_RESULTS:
        return True, s
    # Fuzzy: check if it contains an allowed prefix
    for allowed in ALLOWED_RESULTS:
        if allowed in s:
            return True, allowed
    return False, None


# ─────────────────────────────────────────────────────────────────────────────
# MASTER VALIDATE
# ─────────────────────────────────────────────────────────────────────────────

_VALIDATORS = {
    "candidate_name":    validate_candidate_name,
    "board_university":  validate_board_university,
    "passing_year":      validate_passing_year,
    "percentage":        validate_percentage,
    "cgpa":              validate_cgpa,
    "grade_class":       validate_grade_class,
    "result":            validate_result,
}


def validate_extracted_fields(extracted: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run validation on all extracted fields.

    Returns:
        Dict with only valid fields (invalid ones removed / set to None).
        Adds '_validation_warnings' key for audit.
    """
    validated: Dict[str, Any] = {}
    warnings: list = []

    for field, value in extracted.items():
        validator = _VALIDATORS.get(field)
        if validator is None:
            # Unknown field — pass through unchanged
            validated[field] = value
            continue

        is_valid, clean_value = validator(value)
        if is_valid:
            validated[field] = clean_value
        else:
            warnings.append(f"Field '{field}' failed validation: value={value!r}")
            logger.info("[validator] %s='%s' rejected", field, value)

    if warnings:
        validated["_validation_warnings"] = warnings

    logger.info("[validator] Validated %d/%d fields, %d warnings",
                len(validated), len(extracted), len(warnings))
    return validated


def get_validation_report(extracted: Dict, validated: Dict) -> Dict:
    """Generate a human-readable validation report."""
    report = {}
    for field in _VALIDATORS:
        original = extracted.get(field)
        validated_val = validated.get(field)
        if original is None and validated_val is None:
            report[field] = {"status": "not_found", "original": None, "validated": None}
        elif validated_val is not None:
            report[field] = {"status": "valid", "original": original, "validated": validated_val}
        else:
            report[field] = {"status": "rejected", "original": original, "validated": None}
    return report
