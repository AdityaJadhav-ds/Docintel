"""
app/academic/percentage_engine.py — Percentage & CGPA calculation engine
=========================================================================
Handles:
  - Auto-detect percentage from raw text
  - Calculate percentage from obtained/total marks
  - Validate calculated vs extracted
  - SGPA → CGPA weighted aggregation
"""

from __future__ import annotations
import re
from typing import Optional, List, Dict
from app.core.logger import logger


# ── Percentage detection ──────────────────────────────────────────────────────

_PCT_PATTERNS = [
    r"percentage[:\s]+(\d{1,3}(?:\.\d{1,2})?)\s*%?",
    r"(\d{1,3}(?:\.\d{1,2})?)\s*%",
    r"percent(?:age)?\s*[:\-]\s*(\d{1,3}(?:\.\d{1,2})?)",
    r"aggregate\s*(?:percentage|%)?\s*[:\-]?\s*(\d{1,3}(?:\.\d{1,2})?)",
    r"(\d{2,3}\.\d{2})\s*(?:percent|%|pct)",
]


def extract_percentage_from_text(text: str) -> Optional[float]:
    """Find the first valid percentage value in raw text."""
    for pat in _PCT_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                if 0.0 <= val <= 100.0:
                    logger.debug("[pct_engine] extracted %.2f%% via pattern: %s", val, pat)
                    return round(val, 2)
            except ValueError:
                continue
    return None


def calculate_percentage(obtained: Optional[float], total: Optional[float]) -> Optional[float]:
    """Compute obtained/total * 100 with guard checks."""
    if obtained is None or total is None:
        return None
    if total <= 0:
        return None
    if obtained > total:
        logger.warning("[pct_engine] obtained(%s) > total(%s) — skipping", obtained, total)
        return None
    return round((obtained / total) * 100, 2)


def resolve_percentage(
    extracted_pct: Optional[float],
    obtained: Optional[float],
    total: Optional[float],
    text: Optional[str] = None,
) -> Optional[float]:
    """
    Best-effort percentage resolution:
    1. Use extracted if valid
    2. Calculate from marks
    3. Scan raw text
    """
    if extracted_pct is not None and 0 < extracted_pct <= 100:
        return extracted_pct

    calc = calculate_percentage(obtained, total)
    if calc is not None:
        return calc

    if text:
        return extract_percentage_from_text(text)

    return None


# ── CGPA engine ───────────────────────────────────────────────────────────────

_CGPA_PATTERN = re.compile(
    r"(?:cgpa|cumulative\s+gpa)[:\s\-]*([0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
_SGPA_PATTERN = re.compile(
    r"(?:sgpa|semester\s+gpa|sem\s+gpa)[:\s\-]*([0-9]+(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)


def extract_cgpa_from_text(text: str) -> Optional[float]:
    m = _CGPA_PATTERN.search(text)
    if m:
        val = float(m.group(1))
        if 0 <= val <= 10:
            return round(val, 2)
    return None


def extract_sgpa_values(text: str) -> List[float]:
    """Extract all SGPA values found in text."""
    hits = []
    for m in _SGPA_PATTERN.finditer(text):
        try:
            val = float(m.group(1))
            if 0 <= val <= 10:
                hits.append(round(val, 2))
        except ValueError:
            pass
    return hits


def compute_cgpa_from_semesters(semesters: List[Dict]) -> Optional[float]:
    """
    Weighted CGPA from semester SGPA + credit hours.
    Falls back to simple average if credits missing.
    """
    valid = [(s["sgpa"], s.get("credits")) for s in semesters if s.get("sgpa")]
    if not valid:
        return None

    if all(c is not None for _, c in valid):
        weighted = sum(sgpa * credits for sgpa, credits in valid)
        total_cr = sum(c for _, c in valid)
        if total_cr > 0:
            return round(weighted / total_cr, 2)

    # Simple average fallback
    return round(sum(s for s, _ in valid) / len(valid), 2)


def cgpa_to_percentage(cgpa: float, scale: float = 10.0) -> float:
    """Convert CGPA on a given scale to approximate percentage."""
    return round((cgpa / scale) * 100, 2)
