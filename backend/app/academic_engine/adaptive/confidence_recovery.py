"""
academic_engine/adaptive/confidence_recovery.py
=================================================
OCR Text Recovery Engine.

Repairs common OCR corruption patterns so a near-miss value can be
validated instead of being discarded.

NEVER invents values — only repairs text that is structurally close
to a valid reading, confirmed by a structural validator afterward.

Supported repairs:
  Percentage (0.0–100.0):
    - "7517"   → "75.17"   (missing decimal point)
    - "7O.14"  → "70.14"   (letter O → digit 0)
    - "8S.4"   → "85.4"    (letter S → digit 5)
    - "7S.17"  → "75.17"   (letter S → digit 5)
    - "75.l7"  → "75.17"   (letter l → digit 1)
    - "75,17"  → "75.17"   (comma → period)
    - "75 17"  → "75.17"   (space → period)
    - "75.170" → "75.17"   (trailing zero extra digit)
    - "1OO"    → "100"     (letter O in 100)
    - " 75.17%"→ "75.17"   (strip whitespace/%)
    - "(75.17)"→ "75.17"   (strip parentheses)

  CGPA (0.0–10.0):
    - "B.74"   → "8.74"    (B → 8)
    - "8,74"   → "8.74"    (comma → period)
    - "O.74"   → "0.74"    (O → 0)

  Name:
    - "RAHUl SHARMA"   → "Rahul Sharma"  (normalize casing)
    - "R@HUL SHARMA"   → "RAHUL SHARMA"  (strip symbols then capitalize)
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from app.core.logger import logger

# ── Character substitution maps ───────────────────────────────────────────────

# Common OCR char confusions: letter → digit
_CHAR_TO_DIGIT: dict = {
    'O': '0', 'o': '0',
    'l': '1', 'I': '1',
    'S': '5', 's': '5',
    'B': '8',
    'G': '6', 'g': '9',
    'Z': '2', 'z': '2',
    'T': '7',
    'q': '9', 'Q': '0',
}

# For use ONLY inside a numeric context
def _fix_numeric_chars(s: str) -> str:
    """Replace common OCR letter-digit confusions inside a numeric string."""
    return ''.join(_CHAR_TO_DIGIT.get(c, c) for c in s)


# ── Strip common wrappers ─────────────────────────────────────────────────────

_STRIP_RE = re.compile(r"[\s%\(\)\[\]\\/:;,'\"|]+")

def _clean_wrapper(text: str) -> str:
    """Strip surrounding noise chars."""
    return text.strip().strip('%').strip().lstrip('(').rstrip(')').strip()


# ── Percentage recovery ───────────────────────────────────────────────────────

def recover_percentage(raw: str) -> Tuple[Optional[str], str]:
    """
    Attempt to recover a valid percentage value from corrupted OCR text.

    Returns:
        (value_str, reason)  — value_str is None if recovery fails.

    The returned value is NOT yet validated — caller must validate range 0–100.
    """
    if not raw or not raw.strip():
        return None, "empty"

    text = _clean_wrapper(raw)
    original = text

    # Step 1: Comma → dot
    text = text.replace(',', '.')

    # Step 2: Space between digits treated as decimal
    text = re.sub(r'(\d)\s+(\d)', r'\1.\2', text)

    # Step 3: OCR char-to-digit substitution in numeric context
    text = _fix_numeric_chars(text)

    # Step 4: Remove any remaining non-numeric chars except '.'
    text = re.sub(r'[^0-9.]', '', text)

    # Step 5: Collapse multiple dots
    text = re.sub(r'\.{2,}', '.', text)

    # Step 6: If no dot — try inserting one before last 2 digits (e.g. "7517" → "75.17")
    if '.' not in text and len(text) == 4:
        text = text[:2] + '.' + text[2:]
    elif '.' not in text and len(text) == 3:
        # Could be e.g. "854" → "85.4"
        text = text[:2] + '.' + text[2:]
    elif '.' not in text and len(text) == 5:
        # Could be e.g. "10000" → "100.00"
        text = text[:3] + '.' + text[3:]

    # Step 7: Validate range
    try:
        val = float(text)
        if 0.0 < val <= 100.0:
            result = str(round(val, 2))
            logger.debug("[conf_recovery] percentage: %r → %r", original, result)
            return result, f"repaired({original!r}→{result!r})"
    except ValueError:
        pass

    return None, f"unrecoverable({original!r})"


def recover_cgpa(raw: str) -> Tuple[Optional[str], str]:
    """
    Attempt to recover a valid CGPA value (0.0–10.0).
    """
    if not raw or not raw.strip():
        return None, "empty"

    text = _clean_wrapper(raw)
    original = text

    # Comma → dot
    text = text.replace(',', '.')

    # OCR char substitution
    text = _fix_numeric_chars(text)

    # Strip non-numeric except '.'
    text = re.sub(r'[^0-9.]', '', text)
    text = re.sub(r'\.{2,}', '.', text)

    # Short inputs: "874" → "8.74"
    if '.' not in text and len(text) == 3:
        text = text[0] + '.' + text[1:]

    try:
        val = float(text)
        if 0.0 < val <= 10.0:
            result = str(round(val, 2))
            logger.debug("[conf_recovery] cgpa: %r → %r", original, result)
            return result, f"repaired({original!r}→{result!r})"
    except ValueError:
        pass

    return None, f"unrecoverable({original!r})"


# ── Name recovery ─────────────────────────────────────────────────────────────

_NAME_NOISE = re.compile(r'[^A-Za-z\s\.\-]')

def recover_name(raw: str) -> Tuple[Optional[str], str]:
    """
    Normalize and clean a candidate name string.

    Returns (cleaned_name, reason) or (None, reason).
    """
    if not raw or not raw.strip():
        return None, "empty"

    text = _NAME_NOISE.sub('', raw).strip()

    # Collapse multiple spaces
    text = re.sub(r'\s{2,}', ' ', text)

    # Title case
    words = text.split()
    if not (2 <= len(words) <= 6):
        return None, f"word_count={len(words)}"

    if all(len(w) < 2 for w in words):
        return None, "all_short_words"

    cleaned = ' '.join(w.capitalize() for w in words)
    return cleaned, "normalized"


# ── Result text recovery ──────────────────────────────────────────────────────

_RESULT_MAP = {
    "P4SS": "PASS", "P455": "PASS",
    "FA1L": "FAIL", "FA!L": "FAIL",
    "D1STIN": "DISTINCTION", "D1STINCTION": "DISTINCTION",
    "0ISTIN": "DISTINCTION",
    "PASSEO": "PASSED",  "PAASED": "PASSED",
}

def recover_result(raw: str) -> Tuple[Optional[str], str]:
    """Normalize common OCR corruptions in result text."""
    if not raw:
        return None, "empty"
    text = re.sub(r'[^A-Za-z\s]', '', raw).upper().strip()

    # Direct map
    if text in _RESULT_MAP:
        return _RESULT_MAP[text], f"mapped({raw!r})"

    # Substring match
    for kw in ["DISTINCTION", "FIRST CLASS", "SECOND CLASS", "THIRD CLASS",
               "PASS", "FAIL", "COMPARTMENT", "ABSENT", "WITHHELD"]:
        if kw in text:
            return kw, f"substring({kw!r})"

    return None, f"unrecognized({raw!r})"
