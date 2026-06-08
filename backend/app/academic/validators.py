"""
app/academic/validators.py — Field-level validation for academic documents
==========================================================================
Validates extracted fields; returns list of warning strings.
Does NOT raise exceptions — soft warnings only.
"""

from __future__ import annotations
from typing import Optional, List
from datetime import datetime


_CURRENT_YEAR = datetime.now().year


def validate_marks(obtained: Optional[float], total: Optional[float]) -> List[str]:
    warnings = []
    if obtained is not None and total is not None:
        if obtained > total:
            warnings.append(f"Obtained marks ({obtained}) exceed total marks ({total})")
        if total <= 0:
            warnings.append(f"Invalid total marks: {total}")
        if obtained < 0:
            warnings.append(f"Negative obtained marks: {obtained}")
    return warnings


def validate_percentage(pct: Optional[float]) -> List[str]:
    if pct is None:
        return []
    if pct < 0 or pct > 100:
        return [f"Percentage out of range: {pct}"]
    return []


def validate_gpa(gpa: Optional[float], label: str = "GPA", scale: float = 10.0) -> List[str]:
    if gpa is None:
        return []
    if gpa < 0 or gpa > scale:
        return [f"{label} out of range (0-{scale}): {gpa}"]
    return []


def validate_year(year: Optional[int]) -> List[str]:
    if year is None:
        return []
    if year < 1950 or year > _CURRENT_YEAR + 1:
        return [f"Passing year looks unrealistic: {year}"]
    return []


def validate_subject_marks(subjects: List[dict]) -> List[str]:
    warnings = []
    for s in subjects:
        obt   = s.get("marks_obtained")
        total = s.get("marks_total")
        name  = s.get("subject", "?")
        if obt is not None and total is not None and obt > total:
            warnings.append(f"Subject '{name}': obtained {obt} > total {total}")
    return warnings


def run_all_validations(data: dict, doc_type: str) -> List[str]:
    """Run all relevant validations and return combined warnings."""
    w: List[str] = []

    w += validate_marks(data.get("obtained_marks"), data.get("total_marks"))
    w += validate_percentage(data.get("percentage"))
    w += validate_year(data.get("passing_year"))
    w += validate_subject_marks(data.get("subjects", []))

    if doc_type == "degree":
        w += validate_gpa(data.get("cgpa"), "CGPA")
        for sem in data.get("semesters", []):
            w += validate_gpa(sem.get("sgpa"), f"Sem-{sem.get('semester','?')} SGPA")

    return w
