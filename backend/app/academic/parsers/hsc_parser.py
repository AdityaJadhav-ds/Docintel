"""
app/academic/parsers/hsc_parser.py — HSC / 12th Marksheet extraction
======================================================================
Extends SSC parser with HSC-specific fields (stream, junior college, etc.)
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Any
from app.core.logger import logger
from app.academic.subject_analyzer import extract_subjects
from app.academic.percentage_engine import resolve_percentage, extract_percentage_from_text
from app.academic.parsers.ssc_parser import (
    _find_name, _find_mother_name, _find_seat, _find_board,
    _find_year, _find_total_marks, _find_obtained_marks,
    _find_grade, _find_result, _find_division, _find_school_number,
    _find_cert_number, _find_dob, _anchor,
)


def _find_stream(text: str) -> Optional[str]:
    """Detect Science / Commerce / Arts stream."""
    if re.search(r"\bscience\b", text, re.IGNORECASE):
        return "Science"
    if re.search(r"\bcommerce\b", text, re.IGNORECASE):
        return "Commerce"
    if re.search(r"\barts?\b|\bhumanities\b", text, re.IGNORECASE):
        return "Arts"
    if re.search(r"\bvocational\b", text, re.IGNORECASE):
        return "Vocational"
    patterns = [r"stream\s*[:\-]\s*([A-Za-z ]{3,20})"]
    val = _anchor(text, patterns)
    return val.strip().title() if val else None


def parse_hsc(raw_text: str) -> Dict[str, Any]:
    """
    Extract all HSC fields from raw OCR text.
    Returns dict conforming to HSCData schema.
    """
    logger.info("[hsc_parser] Parsing HSC document (%d chars)", len(raw_text))

    obtained = _find_obtained_marks(raw_text)
    total    = _find_total_marks(raw_text)
    pct_raw  = extract_percentage_from_text(raw_text)
    pct      = resolve_percentage(pct_raw, obtained, total, raw_text)

    result = {
        "document_type":  "hsc",
        "candidate_name": _find_name(raw_text),
        "mother_name":    _find_mother_name(raw_text),
        "seat_number":    _find_seat(raw_text),
        "certificate_no": _find_cert_number(raw_text),
        "board":          _find_board(raw_text),
        "school_number":  _find_school_number(raw_text),
        "stream":         _find_stream(raw_text),
        "passing_year":   _find_year(raw_text),
        "total_marks":    total,
        "obtained_marks": obtained,
        "percentage":     pct,
        "grade":          _find_grade(raw_text),
        "division":       _find_division(raw_text),
        "result":         _find_result(raw_text),
        "dob":            _find_dob(raw_text),
        "subjects":       extract_subjects(raw_text),
    }

    logger.info(
        "[hsc_parser] Done: name=%s stream=%s pct=%s subjects=%d",
        result["candidate_name"], result["stream"], result["percentage"], len(result["subjects"])
    )
    return result
