"""
app/extraction/bank_handlers/detector.py
=========================================
Bank detection and layout confidence scoring.

Rules:
  - Keyword scan on the first N word-boxes only (O(1) in practice)
  - Returns a string tag: "SBI", "KOTAK", "HDFC", "ICICI", "AXIS", "UNKNOWN"
  - No OCR, no ML, no regex-heavy processing
"""
from __future__ import annotations

from typing import Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# Bank signature table
# Each entry: (bank_tag, set_of_uppercase_keywords)
# Keywords are checked with substring match on the uppercased word text.
# Add new banks here — nothing else needs to change.
# ─────────────────────────────────────────────────────────────────────────────

_BANK_SIGNATURES: List[tuple] = [
    ("SBI",   {"STATE BANK OF INDIA", "STATE BANK", "SBIN0", "SBINOO", "STATEMENT OF ACCOUNT"}),
    ("KOTAK", {"KOTAK MAHINDRA", "KOTAK811", "KOTAK BANK", "811"}),
    ("HDFC",  {"HDFC BANK", "HDFCBANK", "HDFC LTD"}),
    ("ICICI", {"ICICI BANK", "ICICIBANK"}),
    ("AXIS",  {"AXIS BANK", "UTIB0"}),
]

# Scan only the first N words — the bank name always appears near the top
_SCAN_LIMIT = 60


def detect_bank(words: List[Dict]) -> str:
    """
    Return the bank tag for the document, or "UNKNOWN".

    O(1) — scans at most _SCAN_LIMIT words × len(_BANK_SIGNATURES) × keywords.
    """
    scan_words = words[:_SCAN_LIMIT]

    for bank_tag, keywords in _BANK_SIGNATURES:
        for w in scan_words:
            text_upper = w["text"].upper()
            for kw in keywords:
                if kw in text_upper:
                    return bank_tag

    return "UNKNOWN"
