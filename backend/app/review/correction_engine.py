"""
app/review/correction_engine.py — Auto-correction suggestion engine
====================================================================
Analyzes field mismatches and generates:
  1. Auto-correction suggestions (can system fix it?)
  2. Correction type classification
  3. Suggested value with explanation

Auto-correctable cases:
  - spacing issues      → collapse whitespace
  - capitalization      → normalize title case
  - minor OCR typo      → use stored value (highest-confidence)
  - merged words        → re-spaced version
  - unicode cleanup     → normalized value
"""

from __future__ import annotations
import re
import unicodedata
from typing import Optional, Dict, List, Tuple
from app.core.logger import logger

try:
    from rapidfuzz import fuzz
    _HAS_RF = True
except ImportError:
    _HAS_RF = False


# ── Correction type registry ──────────────────────────────────────────────────

class CorrectionType:
    SPACING_FIX         = "spacing_fix"
    CAPITALIZATION_FIX  = "capitalization_fix"
    OCR_TYPO_FIX        = "ocr_typo_fix"
    MERGED_WORD_FIX     = "merged_word_fix"
    UNICODE_CLEANUP     = "unicode_cleanup"
    PUNCTUATION_CLEANUP = "punctuation_cleanup"
    MANUAL_REQUIRED     = "manual_required"
    NO_CORRECTION       = "no_correction"


# ── Per-fix detectors & correctors ───────────────────────────────────────────

def _fix_spacing(value: str) -> Tuple[bool, str]:
    """Collapse multiple spaces; strip leading/trailing."""
    fixed = re.sub(r"\s+", " ", value).strip()
    return fixed != value, fixed


def _fix_capitalization(value: str) -> Tuple[bool, str]:
    """Title-case the value."""
    fixed = value.title()
    return fixed != value, fixed


def _fix_unicode(value: str) -> Tuple[bool, str]:
    """NFKD normalize + remove combining characters."""
    original_value = value
    if value is None:
        value = ""
    if isinstance(value, dict):
        value = value.get("value", "")
    if isinstance(value, list):
        value = " ".join([str(v) for v in value])
    value = str(value)
    
    nfkd = unicodedata.normalize("NFKD", value)
    fixed = "".join(c for c in nfkd if not unicodedata.combining(c))
    return fixed != original_value, fixed


def _fix_merged_words(value: str) -> Tuple[bool, str]:
    """Insert space at CamelCase boundaries."""
    fixed = re.sub(r"([a-z])([A-Z])", r"\1 \2", value)
    return fixed != value, fixed


def _fix_punctuation(value: str) -> Tuple[bool, str]:
    """Remove stray punctuation from names/IDs."""
    fixed = re.sub(r"[^\w\s\/\-]", "", value).strip()
    fixed = re.sub(r"\s+", " ", fixed)
    return fixed != value, fixed


def _apply_all_fixes(value: str) -> Tuple[str, List[str]]:
    """
    Apply all auto-fixable corrections in order.
    Returns (corrected_value, list_of_applied_correction_types).
    """
    applied: List[str] = []
    v = value

    changed, v = _fix_unicode(v)
    if changed:
        applied.append(CorrectionType.UNICODE_CLEANUP)

    changed, v = _fix_merged_words(v)
    if changed:
        applied.append(CorrectionType.MERGED_WORD_FIX)

    changed, v = _fix_punctuation(v)
    if changed:
        applied.append(CorrectionType.PUNCTUATION_CLEANUP)

    changed, v = _fix_spacing(v)
    if changed:
        applied.append(CorrectionType.SPACING_FIX)

    changed, v = _fix_capitalization(v)
    if changed:
        applied.append(CorrectionType.CAPITALIZATION_FIX)

    return v, applied


# ── Similarity helpers ────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if _HAS_RF:
        return max(fuzz.ratio(a, b), fuzz.token_sort_ratio(a, b))
    return 100.0 if a.lower() == b.lower() else 0.0


# ── Public API ────────────────────────────────────────────────────────────────

def generate_correction_suggestion(
    field:      str,
    stored:     Optional[str],
    extracted:  Optional[str],
    status:     str,
    score:      float,
) -> Dict:
    """
    Generate an auto-correction suggestion for a single field.

    Returns:
        {
            "field":             str,
            "stored":            str | None,
            "extracted":         str | None,
            "suggested_value":   str | None,   # best suggested value
            "correction_type":   str,
            "auto_fixable":      bool,
            "explanation":       str,
            "confidence_after":  int,          # estimated confidence if fix applied
        }
    """
    if status == "MATCH":
        return {
            "field":            field,
            "stored":           stored,
            "extracted":        extracted,
            "suggested_value":  extracted,
            "correction_type":  CorrectionType.NO_CORRECTION,
            "auto_fixable":     False,
            "explanation":      "Field already matches — no correction needed.",
            "confidence_after": 100,
        }

    if not extracted:
        return {
            "field":            field,
            "stored":           stored,
            "extracted":        extracted,
            "suggested_value":  None,
            "correction_type":  CorrectionType.MANUAL_REQUIRED,
            "auto_fixable":     False,
            "explanation":      "Extracted value is missing — re-upload document or enter manually.",
            "confidence_after": 0,
        }

    # Try auto-fixes on the extracted value
    fixed_extracted, applied_types = _apply_all_fixes(extracted)
    score_after_fix = _similarity(stored or "", fixed_extracted)

    # If fix improved similarity significantly
    if score_after_fix > score + 3:
        correction_type = applied_types[0] if applied_types else CorrectionType.SPACING_FIX
        return {
            "field":            field,
            "stored":           stored,
            "extracted":        extracted,
            "suggested_value":  fixed_extracted,
            "correction_type":  correction_type,
            "auto_fixable":     True,
            "explanation":      (
                f"Applied {', '.join(applied_types)} to extracted value. "
                f"Similarity improved from {score:.0f}→{score_after_fix:.0f}."
            ),
            "confidence_after": int(score_after_fix),
        }

    # POSSIBLE_MATCH with high score → suggest using stored value
    if status == "POSSIBLE_MATCH" and score >= 85:
        return {
            "field":            field,
            "stored":           stored,
            "extracted":        extracted,
            "suggested_value":  stored,
            "correction_type":  CorrectionType.OCR_TYPO_FIX,
            "auto_fixable":     True,
            "explanation":      (
                f"Minor OCR variation detected (score={score:.0f}/100). "
                "Stored value is likely correct — suggest accepting stored value."
            ),
            "confidence_after": 97,
        }

    # Can't auto-fix
    return {
        "field":            field,
        "stored":           stored,
        "extracted":        extracted,
        "suggested_value":  None,
        "correction_type":  CorrectionType.MANUAL_REQUIRED,
        "auto_fixable":     False,
        "explanation":      (
            f"Mismatch score {score:.0f}/100 is too low for auto-correction. "
            "Manual review and correction required."
        ),
        "confidence_after": int(score),
    }


def generate_all_suggestions(comparison_fields: List[Dict]) -> List[Dict]:
    """Run generate_correction_suggestion on all fields in comparison payload."""
    suggestions = []
    for f in comparison_fields:
        suggestion = generate_correction_suggestion(
            field     = f.get("field", ""),
            stored    = f.get("stored"),
            extracted = f.get("extracted"),
            status    = f.get("status", "MISMATCH"),
            score     = f.get("match_score", 0),
        )
        suggestions.append(suggestion)
    return suggestions
