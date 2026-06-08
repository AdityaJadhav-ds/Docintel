"""
app/academic/subject_analyzer.py — Table-aware subject/marks extraction engine
===============================================================================
Extracts subject → marks rows from raw OCR text.

Handles:
  - Standard tabular layouts (Subject | Marks | Total)
  - Broken lines from mobile scans
  - Merged cell artifacts
  - Mixed SSC/HSC/Degree grade columns
"""

from __future__ import annotations
import re
from typing import List, Dict, Optional
from app.core.logger import logger


# ── Grade lookup ──────────────────────────────────────────────────────────────

_GRADE_MAP = {
    "O": "Outstanding", "A+": "Excellent", "A": "Very Good",
    "B+": "Good", "B": "Above Average", "C": "Average",
    "D": "Pass", "F": "Fail", "P": "Pass", "AB": "Absent",
    "E": "Excellent",  # some boards use E
}


def _normalise_grade(g: str) -> str:
    return _GRADE_MAP.get(g.strip().upper(), g.strip())


# ── Known subject patterns ────────────────────────────────────────────────────

# Core SSC/HSC subjects
_SUBJECT_KEYWORDS = [
    r"mathematics?|maths?",
    r"science|physics|chemistry|biology|life\s+science",
    r"english",
    r"hindi|marathi|gujarati|urdu|tamil|telugu|kannada|bengali|punjabi",
    r"social\s+science|history|geography|civics|economics",
    r"computer\s+science|information\s+technology",
    r"accounts?|accountancy",
    r"commerce",
    r"business\s+studies",
    r"environment|evs",
    r"art|drawing|craft",
    r"physical\s+education|sports",
    r"vocational",
    r"sanskrit",
    r"french|german|spanish",
]

_SUBJ_RE = re.compile(
    "|".join(f"(?:{p})" for p in _SUBJECT_KEYWORDS),
    re.IGNORECASE,
)

# Marks patterns: "72", "72/100", "72 out of 100"
_MARKS_RE = re.compile(
    r"\b(\d{1,3})(?:\s*/\s*(\d{2,3}))?\b"
)

# Grade in parentheses or adjacent: (A+), A+, Grade: B
_GRADE_RE = re.compile(
    r"\b([OAABCDFPE]{1,2}\+?)\b"
)


# ── Row-based extraction ──────────────────────────────────────────────────────

def _try_extract_row(line: str, prev_subject: Optional[str] = None) -> Optional[Dict]:
    """
    Try to parse a single line as a subject-marks row.
    Returns dict or None.
    """
    line = line.strip()
    if not line or len(line) < 4:
        return None

    # Check if this line contains a subject keyword
    subj_match = _SUBJ_RE.search(line)
    subject    = None
    if subj_match:
        subject = subj_match.group(0).title()
    elif prev_subject and not _SUBJ_RE.search(line):
        # Might be continuation of marks for prev_subject
        subject = prev_subject

    if not subject:
        return None

    # Extract marks
    marks_found = _MARKS_RE.findall(line)
    obtained    = None
    total       = None

    # Heuristic: first numeric is obtained, second is total if slash present
    for m, t in marks_found:
        try:
            val = int(m)
            if val > 200:
                continue  # Skip seat/cert numbers
            if obtained is None:
                obtained = float(val)
            if t and total is None:
                total = float(int(t))
        except ValueError:
            pass

    # Extract grade
    grade_match = _GRADE_RE.search(line)
    grade       = None
    if grade_match:
        g = grade_match.group(1)
        if g not in ("I", "IN", "OF"):  # exclude common false matches
            grade = _normalise_grade(g)

    return {
        "subject":        subject,
        "marks_obtained": obtained,
        "marks_total":    total,
        "grade":          grade,
    }


# ── Table block extraction ────────────────────────────────────────────────────

def _extract_from_table_block(block: str) -> List[Dict]:
    """
    Parse a multi-line table-like block.
    Expected patterns:
      Mathematics  |  72  |  100  |  A+
      English         65    100    B+
    """
    results: List[Dict] = []
    lines   = block.splitlines()

    for line in lines:
        # Split on pipe, tab, or multiple spaces
        parts = re.split(r"\|+|\t+|\s{3,}", line.strip())
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) < 2:
            continue

        # First non-number part = subject
        subject = None
        nums    = []
        grade   = None

        for p in parts:
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", p):
                nums.append(float(p))
            elif _SUBJ_RE.search(p):
                subject = p.title()
            elif _GRADE_RE.fullmatch(p.strip()) and p not in ("I", "IN"):
                grade = _normalise_grade(p)

        if subject and nums:
            obtained = nums[0] if nums else None
            total    = nums[1] if len(nums) > 1 else None
            results.append({
                "subject":        subject,
                "marks_obtained": obtained,
                "marks_total":    total,
                "grade":          grade,
            })

    return results


# ── Public API ────────────────────────────────────────────────────────────────

def extract_subjects(raw_text: str) -> List[Dict]:
    """
    Master subject extraction.
    Tries table-block parsing first, falls back to line-by-line.
    Deduplicates by subject name.
    """
    if not raw_text:
        return []

    results: List[Dict] = []

    # Strategy 1: table block
    table_results = _extract_from_table_block(raw_text)
    results.extend(table_results)

    # Strategy 2: line-by-line if table yielded <2
    if len(results) < 2:
        prev_subject = None
        for line in raw_text.splitlines():
            row = _try_extract_row(line, prev_subject)
            if row and row.get("marks_obtained") is not None:
                results.append(row)
                prev_subject = row["subject"]

    # Dedup by subject
    seen    = set()
    unique  = []
    for r in results:
        key = r["subject"].lower().replace(" ", "")
        if key not in seen:
            seen.add(key)
            unique.append(r)

    logger.debug("[subject_analyzer] Extracted %d subjects", len(unique))
    return unique
