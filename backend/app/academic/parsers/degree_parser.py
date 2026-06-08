"""
app/academic/parsers/degree_parser.py — Degree / University marksheet extraction
==================================================================================
Handles: Statement of Grades, SGPA/CGPA reports, University transcripts,
semester marksheets, consolidated marksheets.

Key extractions:
  - PRN / enrollment / roll number
  - University name
  - Degree / course name
  - Per-semester SGPA + credits
  - Final CGPA (extracted or computed)
  - Aggregate percentage
  - Subject marks per semester
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Any, List
from app.core.logger import logger
from app.academic.subject_analyzer import extract_subjects
from app.academic.percentage_engine import (
    resolve_percentage, extract_percentage_from_text,
    extract_cgpa_from_text, extract_sgpa_values,
    compute_cgpa_from_semesters, cgpa_to_percentage,
)
from app.academic.parsers.ssc_parser import _anchor, _find_year


# ── Field extractors ──────────────────────────────────────────────────────────

def _find_student_name(text: str) -> Optional[str]:
    patterns = [
        r"student(?:'s)?\s+name\s*[:\-]\s*([A-Z][A-Z\s\.]{3,40})",
        r"name\s+of\s+(?:the\s+)?student\s*[:\-]\s*([A-Z][A-Z\s\.]{3,40})",
        r"candidate(?:'s)?\s+name\s*[:\-]\s*([A-Z][A-Z\s\.]{3,40})",
        r"name\s*[:\-]\s*([A-Z][A-Z\s\.]{4,40})",
    ]
    val = _anchor(text, patterns)
    return re.sub(r"\s+", " ", val).strip().title() if val else None


def _find_prn(text: str) -> Optional[str]:
    patterns = [
        r"\bprn\b\s*[:\-\.#]?\s*([0-9A-Z]{6,20})",
        r"permanent\s+reg(?:istration)?\s+no\.?\s*[:\-]\s*([0-9A-Z]{6,20})",
        r"enroll(?:ment)?\s+no\.?\s*[:\-]\s*([0-9A-Z]{6,20})",
        r"reg(?:istration)?\s+no\.?\s*[:\-]\s*([0-9A-Z]{6,20})",
    ]
    return _anchor(text, patterns)


def _find_seat_number(text: str) -> Optional[str]:
    patterns = [
        r"seat\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,14})",
        r"roll\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,14})",
        r"exam\s+seat\s+no\.?\s*[:\-]\s*([A-Z0-9]{4,14})",
    ]
    return _anchor(text, patterns)


def _find_university(text: str) -> Optional[str]:
    patterns = [
        r"((?:\w+\s+){1,5}university[^\n]{0,30})",
        r"university\s+of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})",
    ]
    val = _anchor(text, patterns)
    return val.strip().title() if val else None


def _find_degree_name(text: str) -> Optional[str]:
    # Common degree abbreviations
    degree_re = re.compile(
        r"\b(b\.?tech|b\.?e\.?|b\.?sc\.?|b\.?com\.?|b\.?ca|b\.?a\.?|"
        r"m\.?tech|m\.?sc\.?|m\.?com\.?|mba|mca|ph\.?d|b\.?arch)\b",
        re.IGNORECASE,
    )
    m = degree_re.search(text)
    if m:
        return m.group(1).upper().replace(".", "").strip()
    return None


def _find_course_name(text: str) -> Optional[str]:
    patterns = [
        r"course\s+name\s*[:\-]\s*([A-Za-z &\(\)]{5,50})",
        r"programme\s*[:\-]\s*([A-Za-z &\(\)]{5,50})",
        r"department\s+of\s+([A-Za-z &]{5,40})",
    ]
    val = _anchor(text, patterns)
    return val.strip().title() if val else None


def _find_result_class(text: str) -> Optional[str]:
    classes = {
        r"first\s+class\s+with\s+distinction": "First Class with Distinction",
        r"first\s+class":                       "First Class",
        r"second\s+class":                      "Second Class",
        r"distinction":                         "Distinction",
        r"pass\s+class":                        "Pass Class",
        r"outstanding":                         "Outstanding",
        r"excellent":                           "Excellent",
    }
    low = text.lower()
    for pat, label in classes.items():
        if re.search(pat, low):
            return label
    return None


def _find_grade(text: str) -> Optional[str]:
    grade_map = {
        r"\boutstanding\b": "Outstanding",
        r"\bexcellent\b":   "Excellent",
        r"\bvery\s+good\b": "Very Good",
        r"\bgood\b":        "Good",
        r"\baverage\b":     "Average",
        r"\bgrade\s+o\b":   "O (Outstanding)",
        r"\bgrade\s+a\b":   "A",
        r"\bgrade\s+b\b":   "B",
    }
    low = text.lower()
    for pat, label in grade_map.items():
        if re.search(pat, low):
            return label
    return None


# ── Semester extraction ───────────────────────────────────────────────────────

def _extract_semesters(text: str) -> List[Dict]:
    """
    Find all semester SGPA entries from text.
    Handles patterns like:
      Sem I : SGPA 8.25
      Semester 3 SGPA: 7.50
    """
    sem_re = re.compile(
        r"sem(?:ester)?\s*[:\-.\s]*([1-8iivx]+)\s*[:\-]?\s*"
        r"(?:sgpa|gpa)?\s*[:\-]?\s*([0-9]+\.[0-9]{1,2})",
        re.IGNORECASE,
    )

    roman = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}

    semesters: List[Dict] = []
    for m in sem_re.finditer(text):
        sem_num_raw = m.group(1).strip().lower()
        try:
            sem_num = int(sem_num_raw)
        except ValueError:
            sem_num = roman.get(sem_num_raw, 0)

        try:
            sgpa = float(m.group(2))
            if 0 <= sgpa <= 10:
                semesters.append({"semester": sem_num, "sgpa": sgpa})
        except ValueError:
            pass

    # Deduplicate by semester number
    seen  = set()
    dedup = []
    for s in semesters:
        if s["semester"] not in seen:
            seen.add(s["semester"])
            dedup.append(s)

    return sorted(dedup, key=lambda x: x["semester"])


# ── Public API ────────────────────────────────────────────────────────────────

def parse_degree(raw_text: str) -> Dict[str, Any]:
    """
    Extract all Degree/University fields from raw OCR text.
    """
    logger.info("[degree_parser] Parsing Degree document (%d chars)", len(raw_text))

    semesters  = _extract_semesters(raw_text)
    cgpa_text  = extract_cgpa_from_text(raw_text)
    cgpa_calc  = compute_cgpa_from_semesters(semesters) if semesters else None
    cgpa       = cgpa_text or cgpa_calc

    pct_raw    = extract_percentage_from_text(raw_text)
    pct_cgpa   = cgpa_to_percentage(cgpa) if cgpa and not pct_raw else None
    percentage = pct_raw or pct_cgpa

    result = {
        "document_type":       "degree",
        "student_name":        _find_student_name(raw_text),
        "prn":                 _find_prn(raw_text),
        "seat_number":         _find_seat_number(raw_text),
        "university":          _find_university(raw_text),
        "degree_name":         _find_degree_name(raw_text),
        "course_name":         _find_course_name(raw_text),
        "passing_year":        _find_year(raw_text),
        "cgpa":                cgpa,
        "aggregate_percentage": percentage,
        "result_class":        _find_result_class(raw_text),
        "grade":               _find_grade(raw_text),
        "semesters":           semesters,
        "all_subjects":        extract_subjects(raw_text),
    }

    logger.info(
        "[degree_parser] Done: name=%s uni=%s cgpa=%s sems=%d",
        result["student_name"], result["university"], result["cgpa"], len(result["semesters"])
    )
    return result
