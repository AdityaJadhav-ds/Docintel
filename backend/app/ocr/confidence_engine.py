"""
app/ocr/confidence_engine.py
==============================
Compatibility shim — provides calculate_field_confidence() used by parsers.

Function signature matches the calling convention in aadhaar_parser.py and
pan_parser.py:
    calculate_field_confidence(field_name, value, clean_text, variant_texts)

Returns a field-level confidence score (0–100).
"""
from __future__ import annotations
from typing import Any, Dict, Optional


def calculate_field_confidence(
    field_name: str,
    value: Optional[Any],
    clean_text: str = "",
    variant_texts: Optional[Dict[str, str]] = None,
) -> float:
    """
    Return a field-level confidence score (0–100).

    Logic:
      - value is None → 0
      - value found in clean_text → +60 base
      - value found in at least one variant_text → +20 bonus
      - non-empty value regardless of text match → +30 base

    Capped at 100.0.
    """
    if value is None:
        return 0.0

    str_value = str(value).strip()
    if not str_value:
        return 0.0

    score = 30.0  # base: field was extracted

    # Presence in primary OCR text
    if clean_text and str_value.lower() in clean_text.lower():
        score += 60.0

    # Bonus: confirmed in at least one variant
    if variant_texts:
        for vt in variant_texts.values():
            if vt and str_value.lower() in vt.lower():
                score += 20.0
                break

    return round(min(score, 100.0), 1)
