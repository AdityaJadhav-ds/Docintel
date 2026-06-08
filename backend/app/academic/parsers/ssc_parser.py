"""
app/academic/parsers/ssc_parser.py — SSC / 10th Marksheet extraction
======================================================================
Extracts all fields from Maharashtra SSC, CBSE 10th, ICSE 10th
and generic state board SSC certificates.

Uses:
  - Label-anchor regex extraction
  - Line-context scanning
  - Semantic candidate ranking
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Any, List
from app.core.logger import logger
from app.academic.subject_analyzer import extract_subjects
from app.academic.percentage_engine import resolve_percentage, extract_percentage_from_text


# ── Helper: label-anchor extraction ──────────────────────────────────────────

def _anchor(text: str, patterns: List[str]) -> Optional[str]:
    """Find value following any of the label patterns."""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = m.group(1).strip()
                if val:
                    return val
            except IndexError:
                pass
    return None


def _find_name(text: str) -> Optional[str]:
    patterns = [
        r"candidate(?:'s)?\s+name\s*[:\-]\s*([A-Z][A-Z\s\.]{2,40})",
        r"student(?:'s)?\s+name\s*[:\-]\s*([A-Z][A-Z\s\.]{2,40})",
        r"name\s+of\s+(?:the\s+)?candidate\s*[:\-]\s*([A-Z][A-Z\s\.]{2,40})",
        r"name\s*[:\-]\s*([A-Z][A-Z\s\.]{4,40})",
    ]
    val = _anchor(text, patterns)
    if val:
        return re.sub(r"\s+", " ", val).strip().title()
    return None


def _find_mother_name(text: str) -> Optional[str]:
    patterns = [
        r"mother(?:'s)?\s+name\s*[:\-]\s*([A-Z][A-Z\s\.]{2,40})",
        r"name\s+of\s+mother\s*[:\-]\s*([A-Z][A-Z\s\.]{2,40})",
    ]
    val = _anchor(text, patterns)
    return val.title() if val else None


def _find_seat(text: str) -> Optional[str]:
    patterns = [
        r"seat\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,12})",
        r"exam\s+seat\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,12})",
        r"roll\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,12})",
    ]
    return _anchor(text, patterns)


def _find_board(text: str) -> Optional[str]:
    patterns = [
        r"(maharashtra\s+state\s+board[^\n]{0,40})",
        r"(cbse[^\n]{0,20})",
        r"(central\s+board[^\n]{0,30})",
        r"(icse[^\n]{0,20})",
        r"(council\s+for\s+the\s+indian\s+school[^\n]{0,30})",
        r"(board\s+of\s+secondary\s+education[^\n]{0,30})",
        r"(\w+\s+state\s+board[^\n]{0,30})",
    ]
    val = _anchor(text, patterns)
    return val.strip().title() if val else None


def _find_year(text: str) -> Optional[int]:
    patterns = [
        r"(?:march|october|november)\s*[,\-]\s*(20[0-2]\d|19[89]\d)",
        r"year\s*[:\-]\s*(20[0-2]\d|19[89]\d)",
        r"(?:passing|passed)\s+in\s+(20[0-2]\d|19[89]\d)",
        r"examination\s+(20[0-2]\d|19[89]\d)",
    ]
    val = _anchor(text, patterns)
    if val:
        try:
            return int(val)
        except ValueError:
            pass
    # Fallback: first 4-digit year in 1990-2026
    m = re.search(r"\b((?:19[89]|20[0-2])\d)\b", text)
    return int(m.group(1)) if m else None


def _find_marks(text: str, label: str) -> Optional[float]:
    patterns = [
        rf"{label}\s+marks?\s*[:\-]\s*(\d{{2,4}})",
        rf"(\d{{2,4}})\s*(?:/|out\s+of)\s*\d{{2,4}}(?=.*{label})",
    ]
    val = _anchor(text, patterns)
    if val:
        try:
            return float(val)
        except ValueError:
            pass
    return None


def _find_total_marks(text: str) -> Optional[float]:
    patterns = [
        r"total\s+marks?\s*[:\-]\s*(\d{2,4})",
        r"maximum\s+marks?\s*[:\-]\s*(\d{2,4})",
        r"out\s+of\s*[:\-]?\s*(\d{2,4})",
    ]
    val = _anchor(text, patterns)
    return float(val) if val else None


def _find_obtained_marks(text: str) -> Optional[float]:
    patterns = [
        r"(?:marks?|marks?\s+obtained|total\s+obtained)\s*[:\-]\s*(\d{2,4})",
        r"obtained\s*[:\-]\s*(\d{2,4})",
        r"grand\s+total\s*[:\-]\s*(\d{2,4})",
    ]
    val = _anchor(text, patterns)
    return float(val) if val else None


def _find_grade(text: str) -> Optional[str]:
    grade_map = {
        r"\bdistinction\b": "DISTINCTION",
        r"\bfirst\s+class\b": "FIRST CLASS",
        r"\bsecond\s+class\b": "SECOND CLASS",
        r"\bpass\s+class\b": "PASS CLASS",
        r"\bgrade\s+[:\-]\s*([OABCDF][+]?)": None,  # capture
    }
    low = text.lower()
    for pat, label in grade_map.items():
        m = re.search(pat, low)
        if m:
            if label:
                return label
            try:
                return m.group(1).upper()
            except IndexError:
                pass
    return None


def _find_result(text: str) -> Optional[str]:
    if re.search(r"\bpassed\b|\bpass\b", text, re.IGNORECASE):
        return "PASSED"
    if re.search(r"\bfailed\b|\bfail\b|\bwithheld\b", text, re.IGNORECASE):
        return "FAILED"
    return None


def _find_division(text: str) -> Optional[str]:
    m = re.search(r"\b(first|second|third|distinction)\s+division\b", text, re.IGNORECASE)
    return m.group(0).title() if m else None


def _find_school_number(text: str) -> Optional[str]:
    patterns = [
        r"school\s+(?:index\s+)?no\.?\s*[:\-]\s*([A-Z0-9]{4,12})",
        r"school\s+code\s*[:\-]\s*([A-Z0-9]{4,12})",
    ]
    return _anchor(text, patterns)


def _find_cert_number(text: str) -> Optional[str]:
    patterns = [
        r"certificate\s+no\.?\s*[:\-]\s*([A-Z0-9\-]{4,20})",
        r"cert\.\s*no\.?\s*[:\-]\s*([A-Z0-9\-]{4,20})",
    ]
    return _anchor(text, patterns)


def _find_dob(text: str) -> Optional[str]:
    patterns = [
        r"(?:date\s+of\s+birth|dob)\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"(?:born\s+on)\s*[:\-]\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\b",
    ]
    return _anchor(text, patterns)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_ssc(raw_text: str) -> Dict[str, Any]:
    """
    Extract all SSC fields from raw OCR text.
    Returns a dict conforming to SSCData schema.
    """
    logger.info("[ssc_parser] Parsing SSC document (%d chars)", len(raw_text))

    obtained = _find_obtained_marks(raw_text)
    total    = _find_total_marks(raw_text)
    pct_raw  = extract_percentage_from_text(raw_text)
    pct      = resolve_percentage(pct_raw, obtained, total, raw_text)

    result = {
        "document_type":  "ssc",
        "candidate_name": _find_name(raw_text),
        "mother_name":    _find_mother_name(raw_text),
        "seat_number":    _find_seat(raw_text),
        "certificate_no": _find_cert_number(raw_text),
        "board":          _find_board(raw_text),
        "school_number":  _find_school_number(raw_text),
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
        "[ssc_parser] Done: name=%s year=%s pct=%s subjects=%d",
        result["candidate_name"], result["passing_year"], result["percentage"], len(result["subjects"])
    )
    return result
