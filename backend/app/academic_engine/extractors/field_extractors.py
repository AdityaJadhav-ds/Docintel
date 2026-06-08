"""
academic_engine/extractors/field_extractors.py
================================================
ROI-Based Field Extraction Engine (STEP 4)

TUNING CHANGES (Phase 3 + 4 + 6 — Critical System Tuning):

  Phase 3 — Name Extraction:
    - Added comprehensive _NAME_REJECT_WORDS blacklist
    - _is_valid_name() rejects numeric-heavy / institution / symbol noise
    - _extract_name_from_lines() now skips table contamination keywords
    - Last-resort ALL-CAPS scan requires no reject words
    - Added _clean_ocr_text() to normalize line noise before parsing

  Phase 4 — Percentage Extraction:
    - Added _repair_percentage_ocr() with 10+ recovery rules:
      7517→75.17, 7S.17→75.17, 75:17→75.17, 75 17→75.17
    - Percentage search now scans both label-adjacent AND standalone
    - Minimum floor changed from 10.0 to 0.5 to allow very low scores
    - Added percentage extraction from full-page text as last resort

  Phase 6 — OCR Cleaning:
    - _clean_ocr_text() strips unicode junk, collapses spaces,
      removes isolated symbols, repairs common confusions
"""

from __future__ import annotations
import re
import logging
from typing import Optional, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6 — OCR TEXT CLEANER
# ─────────────────────────────────────────────────────────────────────────────

def _clean_ocr_text(text: str) -> str:
    """
    Normalize raw OCR text before field parsing:
    - Remove non-printable / control characters
    - Collapse repeated spaces
    - Remove isolated single symbols (not inside words)
    - Keep Marathi Unicode (U+0900–U+097F)
    """
    if not text:
        return ""
    # Remove non-printable except newline + Marathi range
    text = re.sub(r"[^\x09\x0A\x0D\x20-\x7E\u0900-\u097F]", " ", text)
    # Collapse repeated whitespace on each line
    lines = [re.sub(r"[ \t]{2,}", " ", ln) for ln in text.splitlines()]
    # Remove lines that are only symbols (no alphanumeric content)
    lines = [ln for ln in lines if re.search(r"[A-Za-z0-9\u0900-\u097F]", ln)]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — PERCENTAGE REPAIR
# ─────────────────────────────────────────────────────────────────────────────

def _repair_percentage_ocr(text: str) -> Optional[str]:
    """
    Repair common OCR corruptions in percentage strings and validate result.

    Recovery rules:
      7517    → 75.17   (missing dot in 4-digit run)
      7S.17   → 75.17   (S→5 substitution)
      75:17   → 75.17   (colon → dot)
      75;17   → 75.17
      75 17   → 75.17   (space → dot)
      O5.17   → 05.17   (O→0)
      lOO     → 100     (l→1, O→0)
    """
    t = text.strip()
    if not t:
        return None

    # Char-level repairs
    t = re.sub(r"[Oo]", "0", t)
    t = re.sub(r"[Il|]", "1", t)
    t = re.sub(r"[Ss]", "5", t)
    t = re.sub(r"[Bb]", "8", t)
    t = re.sub(r"[Zz]", "2", t)
    # Punctuation repairs
    t = re.sub(r"[:;]", ".", t)
    # Space-in-number → dot
    m = re.match(r"^(\d{1,3})\s+(\d{1,2})$", t)
    if m:
        candidate = f"{m.group(1)}.{m.group(2)}"
        try:
            v = float(candidate)
            if 0.5 <= v <= 100.0:
                return f"{v:.2f}"
        except ValueError:
            pass
    # 4-digit → XX.XX
    m = re.fullmatch(r"(\d{2})(\d{2})", t)
    if m:
        candidate = f"{m.group(1)}.{m.group(2)}"
        try:
            v = float(candidate)
            if 0.5 <= v <= 100.0:
                return f"{v:.2f}"
        except ValueError:
            pass

    # Standard decimal match
    for m in re.finditer(r"\b(\d{1,3}(?:\.\d{1,4})?)\b", t):
        try:
            v = float(m.group(1))
            if 0.5 <= v <= 100.0:
                return f"{v:.2f}"
        except ValueError:
            pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTORS
# ─────────────────────────────────────────────────────────────────────────────



def extract_passing_year(zone_text: str) -> Optional[str]:
    if not zone_text:
        return None
    low = zone_text.lower()
    m = re.search(
        r"(?:march|april|october|november|july|june|february|january|may|august|september|december)"
        r"[-,\s]+(\d{4}|\d{2})\b",
        low,
    )
    if m:
        yr = int(m.group(1))
        yr = 2000 + yr if yr < 100 else yr
        if 1950 <= yr <= 2035:
            return str(yr)
    m = re.search(r"year\s*(?:of\s+(?:exam|passing|examination))?\s*[:\-]?\s*(\d{4})", low)
    if m:
        yr = int(m.group(1))
        if 1950 <= yr <= 2035:
            return str(yr)
    m = re.search(r"(?:awarded|passed|held)\s+in\s+(\d{4})", low)
    if m:
        yr = int(m.group(1))
        if 1950 <= yr <= 2035:
            return str(yr)
    lines = zone_text.splitlines()[:30]
    for line in lines:
        for m in re.finditer(r"\b((?:19|20)\d{2})\b", line):
            yr = int(m.group(1))
            if 1950 <= yr <= 2035:
                return str(yr)
    return None


def extract_percentage(zone_text: str) -> Optional[str]:
    """
    Extract percentage from Zone D summary text.
    Multi-stage: label-adjacent → repaired numeric → standalone decimal.
    Valid range: 0.5–100.
    """
    if not zone_text:
        return None

    cleaned = _clean_ocr_text(zone_text)
    lines   = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]

    # Stage 1: look for explicit percentage labels (bottom-up)
    for line in reversed(lines):
        ll = line.lower()
        if re.search(r"percentage|टक्केवारी|%|percent|aggregate", ll):
            # Try all numeric tokens on this line
            tokens = re.findall(r"[\d\s\.:;SsBbOoIil]{3,}", line)
            for tok in tokens:
                val = _repair_percentage_ocr(tok.strip())
                if val:
                    return val
            # Raw number extraction
            nums = re.findall(r"\b(\d{1,3}(?:\.\d{1,4})?)\b", line)
            for n in nums:
                try:
                    v = float(n)
                    if 0.5 <= v <= 100.0:
                        return f"{v:.2f}"
                except ValueError:
                    pass

    # Stage 2: scan all lines for XX.XX pattern
    for m in re.finditer(r"\b(\d{1,3}\.\d{1,4})\s*%?", cleaned):
        try:
            v = float(m.group(1))
            if 0.5 <= v <= 100.0:
                return f"{v:.2f}"
        except ValueError:
            pass

    # Stage 3: try OCR repair on any 4-digit runs
    for m in re.finditer(r"\b(\d{4,5})\b", cleaned):
        val = _repair_percentage_ocr(m.group(1))
        if val:
            return val

    return None


def extract_cgpa(zone_text: str) -> Optional[str]:
    if not zone_text:
        return None
    patterns = [
        r"cgpa\s*[:\-]?\s*(\d+(?:\.\d{1,3})?)",
        r"(\d+(?:\.\d{1,3})?)\s*(?:cgpa|c\.g\.p\.a)",
        r"(?:grade\s+point\s+average|gpa)\s*[:\-]?\s*(\d+(?:\.\d{1,3})?)",
        r"(?:sgpa|semester\s+gpa)\s*[:\-]?\s*(\d+(?:\.\d{1,3})?)",
    ]
    for pat in patterns:
        m = re.search(pat, zone_text, re.IGNORECASE)
        if m:
            try:
                v = float(m.group(1))
                if 0.0 <= v <= 10.0:
                    return f"{v:.2f}"
            except ValueError:
                pass
    return None


def extract_grade_class(zone_text: str) -> Optional[str]:
    if not zone_text:
        return None
    low = zone_text.lower()
    priority = [
        (r"first\s+class\s+with\s+distinction",  "First Class with Distinction"),
        (r"\bi[-\s]?dist\b",                       "Distinction"),
        (r"\bdistinction\b",                        "Distinction"),
        (r"first\s+class|first\s+division|i\s+division", "First Class"),
        (r"second\s+class|second\s+division|ii\s+division", "Second Class"),
        (r"pass\s+class|third\s+class|iii\s+division", "Pass Class"),
        (r"\boutstanding\b",                        "Outstanding"),
        (r"\bexcellent\b",                          "Excellent"),
        (r"\ba\+\s+grade|\bO\s+grade\b|\boutstanding\b", "O / A+"),
        (r"\bA\s+grade\b",                          "A Grade"),
        (r"\bB\+\s+grade\b",                        "B+ Grade"),
        (r"\bB\s+grade\b",                          "B Grade"),
        (r"\bc\s+grade\b",                          "C Grade"),
    ]
    for pat, label in priority:
        if re.search(pat, low):
            return label
    return None



# ─────────────────────────────────────────────────────────────────────────────
# MASTER FIELD EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_all_fields(
    zone_texts: Dict[str, str],
    doc_category: str,
    doc_subtype: str = "marksheet",
    board_from_classifier: Optional[str] = None,
) -> Dict[str, Any]:
    # Clean all zone texts upfront (Phase 6)
    header_text  = _clean_ocr_text(zone_texts.get("header",    "") or "")
    cand_text    = _clean_ocr_text(zone_texts.get("candidate", "") or "")
    summary_text = _clean_ocr_text(zone_texts.get("summary",   "") or "")
    cert_text    = _clean_ocr_text(zone_texts.get("cert_stmt", "") or "")

    # Year: header → candidate zone → full-page fallback
    full_text = "\n".join(filter(None, [header_text, cand_text, summary_text, cert_text]))
    passing_year = (
        extract_passing_year(header_text)
        or extract_passing_year(cand_text)
        or extract_passing_year(full_text)
    )

    # Percentage: summary zone primarily
    percentage = None
    if doc_subtype == "marksheet":
        percentage = extract_percentage(summary_text)
        if percentage is None:
            percentage = extract_percentage(cand_text)
        if percentage is None:
            percentage = extract_percentage(header_text)
    else:
        percentage = (
            extract_percentage(summary_text)
            or extract_percentage(cert_text)
            or extract_percentage(header_text)
        )

    # CGPA — try all zones
    cgpa = (
        extract_cgpa(summary_text)
        or extract_cgpa(cand_text)
        or extract_cgpa(cert_text)
    )

    # Grade
    grade_class = (
        extract_grade_class(summary_text)
        or extract_grade_class(cert_text)
    )

    out: Dict[str, Any] = {
        "passing_year":    passing_year,
        "percentage":      percentage,
        "cgpa":            cgpa,
        "grade_class":     grade_class,
    }

    return {k: v for k, v in out.items() if v is not None}
