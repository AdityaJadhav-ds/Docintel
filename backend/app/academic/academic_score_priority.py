"""
app/academic/academic_score_priority.py — Academic Score Priority Engine
=========================================================================
Business rule: Only the highest-priority academic score is retained in the
output dict.  Lower-priority indicators are stripped to keep the UI clean.

Priority ladder:
  1. CGPA           → show cgpa only
  2. Percentage      → show percentage only
  3. Grade / Result  → show grade/result only
  4. Marks           → show obtained_marks + total_marks (last resort)

Usage:
    from app.academic.academic_score_priority import apply_score_priority
    cleaned = apply_score_priority(extracted_dict)
"""

from __future__ import annotations
from typing import Any, Dict, Optional


def apply_score_priority(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Mutates *a copy* of `data` so that only the highest-priority academic
    score field(s) remain.  All lower-priority numeric indicators are removed.

    Returns the cleaned dict.
    """
    out = dict(data)

    cgpa       = out.get("cgpa")
    percentage = out.get("percentage")
    grade      = out.get("grade")
    result     = out.get("result")
    obtained   = out.get("obtained_marks")
    total      = out.get("total_marks")

    # ── CASE 1: CGPA exists ──────────────────────────────────────────────────
    if cgpa is not None:
        # Keep: cgpa, grade, result
        # Drop: percentage, obtained_marks, total_marks
        out.pop("percentage",     None)
        out.pop("obtained_marks", None)
        out.pop("total_marks",    None)
        return out

    # ── CASE 2: Percentage exists ────────────────────────────────────────────
    if percentage is not None:
        # Keep: percentage, grade, result
        # Drop: obtained_marks, total_marks
        out.pop("obtained_marks", None)
        out.pop("total_marks",    None)
        return out

    # ── CASE 3: Grade / Result only ──────────────────────────────────────────
    if grade is not None or result is not None:
        # Keep: grade, result
        # Drop: obtained_marks, total_marks (no numeric aggregate exists)
        out.pop("obtained_marks", None)
        out.pop("total_marks",    None)
        return out

    # ── CASE 4: Marks only (last resort) ────────────────────────────────────
    # Keep whatever marks exist — nothing to strip
    return out


def get_primary_score_label(data: Dict[str, Any]) -> Optional[str]:
    """
    Returns a human-readable label for the primary score shown in the UI.
    Used for logging / audit trails.
    """
    if data.get("cgpa")       is not None: return "CGPA"
    if data.get("percentage") is not None: return "PERCENTAGE"
    if data.get("grade")      is not None: return "GRADE"
    if data.get("result")     is not None: return "RESULT"
    if data.get("obtained_marks") is not None: return "MARKS"
    return None
