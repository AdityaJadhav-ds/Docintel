"""
app/matchers/normalizer.py — Field normalization engine
========================================================
Normalizes extracted and stored data before comparison:
  - lowercase
  - unicode NFKD decomposition
  - remove punctuation / symbols
  - collapse whitespace
  - standardize date formats
"""

from __future__ import annotations
import re
import unicodedata
from typing import Optional


from app.core.logger import logger

def _safe_string(value) -> str:
    """Extract string from dict/list and convert to string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("value", "")
    if isinstance(value, list):
        value = " ".join([str(v) for v in value])
    return str(value)

def _strip_accents(text: str) -> str:
    """Remove diacritics (ñ → n, é → e, etc.)."""
    try:
        if text is None:
            text = ""
        if isinstance(text, dict):
            text = text.get("value", "")
        if isinstance(text, list):
            text = " ".join([str(v) for v in text])
        text = str(text)
        
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))
    except Exception as e:
        logger.error(f"NORMALIZE FAILED in _strip_accents: {type(text)} | {text}")
        raise

def normalize_name(name) -> str:
    """Return a normalized name string for fuzzy matching."""
    s = _safe_string(name)
    if not s:
        return ""
    s = _strip_accents(s)
    s = s.lower()
    s = re.sub(r"[^a-z\s]", " ", s)     # keep only alpha + space
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_date(raw: str) -> Optional[str]:
    """
    Try to normalize various date formats into DD/MM/YYYY.
    Handles: DD/MM/YYYY, DD-MM-YYYY, YYYY
    """
    raw = raw.strip()
    # DD/MM/YYYY or DD-MM-YYYY
    m = re.fullmatch(r"(\d{2})[\/\-](\d{2})[\/\-](\d{4})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    # YYYY only (Year of Birth)
    m = re.fullmatch(r"(\d{4})", raw)
    if m:
        return m.group(1)            # keep year-only for comparison
    return raw


def normalize_dob(dob) -> str:
    s = _safe_string(dob)
    if not s:
        return ""
    return _parse_date(s) or ""


def normalize_id_number(id_num) -> str:
    """Strip all whitespace/dashes from ID number for exact comparison."""
    s = _safe_string(id_num)
    if not s:
        return ""
    return re.sub(r"[\s\-]", "", s.strip().upper())
