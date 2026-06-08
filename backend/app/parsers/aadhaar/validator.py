"""
app/parsers/aadhaar/validator.py — Aadhaar field validators and normalisers
===========================================================================
Provides:
  validate_*  — bool checks that a value is plausible for that field
  normalize_* — convert raw OCR strings to canonical representation
"""

from __future__ import annotations

import re
from typing import Optional

from app.core.logger import logger
from . import rules as R


# ─────────────────────────────────────────────────────────────────────────────
# AADHAAR NUMBER
# ─────────────────────────────────────────────────────────────────────────────

def _verhoeff_check(number: str) -> bool:
    """
    Verhoeff checksum algorithm for Aadhaar number validation.
    Returns True if the number passes the checksum.
    """
    d = [
        [0,1,2,3,4,5,6,7,8,9],
        [1,2,3,4,0,6,7,8,9,5],
        [2,3,4,0,1,7,8,9,5,6],
        [3,4,0,1,2,8,9,5,6,7],
        [4,0,1,2,3,9,5,6,7,8],
        [5,9,8,7,6,0,4,3,2,1],
        [6,5,9,8,7,1,0,4,3,2],
        [7,6,5,9,8,2,1,0,4,3],
        [8,7,6,5,9,3,2,1,0,4],
        [9,8,7,6,5,4,3,2,1,0],
    ]
    p = [
        [0,1,2,3,4,5,6,7,8,9],
        [1,5,7,6,2,8,3,0,9,4],
        [5,8,0,3,7,9,6,1,4,2],
        [8,9,1,6,0,4,3,5,2,7],
        [9,4,5,3,1,2,6,8,7,0],
        [4,2,8,6,5,7,3,9,0,1],
        [2,7,9,3,8,0,6,4,1,5],
        [7,0,4,6,9,1,3,2,5,8],
    ]
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]

    digits = [int(c) for c in reversed(number)]
    c = 0
    for i, digit in enumerate(digits):
        c = d[c][p[i % 8][digit]]
    return c == 0


def validate_aadhaar_number(digits: str) -> bool:
    """
    Validate a 12-digit string as an Aadhaar number:
      1. Must be exactly 12 digits
      2. First digit must not be 0 or 1 (UIDAI rule)
      3. First 4 digits must not look like a year (1800–2099)
      4. Must not have all-zero groups
      5. Verhoeff checksum (optional, logged if fails but not rejected)
    """
    if not digits or not digits.isdigit() or len(digits) != 12:
        return False
    if digits[0] in ("0", "1"):
        return False
    first4 = int(digits[:4])
    if 1800 <= first4 <= 2099:
        return False
    if digits[:4] == "0000" or digits[4:8] == "0000" or digits[8:] == "0000":
        return False

    # Verhoeff check (informational)
    try:
        if not _verhoeff_check(digits):
            logger.debug("[aadhaar_validator] Verhoeff check failed for %s", digits)
            # NOTE: We do NOT reject on checksum failure alone — OCR can corrupt
            # the last digit, and we still want a useful result.
    except Exception:
        pass

    return True


def normalize_aadhaar(digits: str) -> str:
    """Format 12 digits as 'XXXX XXXX XXXX'."""
    d = re.sub(r"\D", "", digits)
    if len(d) != 12:
        return digits
    return f"{d[:4]} {d[4:8]} {d[8:]}"


# ─────────────────────────────────────────────────────────────────────────────
# DATE OF BIRTH
# ─────────────────────────────────────────────────────────────────────────────

def normalize_dob(raw: str) -> Optional[str]:
    """
    Convert a raw date string to DD/MM/YYYY.
    Handles: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, 2-digit year variants.
    Returns None if the date looks invalid.
    """
    raw = raw.strip()
    # Apply OCR digit corrections
    corrected = "".join(R.OCR_DIGIT_MAP.get(c, c) for c in raw)

    # Full date: DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    m = re.fullmatch(r"(\d{2})[/\-\.](\d{2})[/\-\.](\d{4})", corrected)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2025:
            return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    # Short year
    m = re.fullmatch(r"(\d{2})[/\-\.](\d{2})[/\-\.](\d{2})", corrected)
    if m:
        yy = int(m.group(3))
        full_yr = 2000 + yy if yy <= 25 else 1900 + yy
        day, month = int(m.group(1)), int(m.group(2))
        if 1 <= day <= 31 and 1 <= month <= 12:
            return f"{m.group(1)}/{m.group(2)}/{full_yr}"

    return None


def validate_dob(dob: str) -> bool:
    """Return True if dob is a plausible normalised date string."""
    if not dob:
        return False
    # Year-only is acceptable
    if re.fullmatch(r"\d{4}", dob):
        yr = int(dob)
        return 1900 <= yr <= 2025
    # Full date
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", dob)
    if not m:
        return False
    d, mo, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= yr <= 2025


# ─────────────────────────────────────────────────────────────────────────────
# GENDER
# ─────────────────────────────────────────────────────────────────────────────

def normalize_gender(raw: str) -> Optional[str]:
    lw = raw.lower().strip()
    if lw in ("male", "mele", "maie", "mae", "m"):
        return "Male"
    if lw in ("female", "femal", "femafe", "f"):
        return "Female"
    return None


def validate_gender(gender: str) -> bool:
    return gender in ("Male", "Female")


# ─────────────────────────────────────────────────────────────────────────────
# NAME
# ─────────────────────────────────────────────────────────────────────────────

def validate_name(candidate: str) -> bool:
    """
    Validate that a candidate string is a plausible human name.

    Rules (in order):
      1. Length: NAME_MIN_LEN to NAME_MAX_LEN
      2. Character set: alpha + spaces + . - ' only
      3. Word count: 1 to NAME_MAX_WORDS
      4. No address/label words
      5. No impossible consonant clusters (garbled Devanagari detection)
      6. No trailing punctuation on individual words
      7. No 4+ letter words without a vowel
      8. Not entirely made of stop words
    """
    stripped = candidate.strip()

    if len(stripped) < R.NAME_MIN_LEN or len(stripped) > R.NAME_MAX_LEN:
        return False

    if not R.NAME_CHAR_RE.fullmatch(stripped):
        return False

    words = stripped.split()
    if not (R.NAME_MIN_WORDS <= len(words) <= R.NAME_MAX_WORDS):
        return False

    lower_words = [w.lower() for w in words]

    # Check for label words
    if any(w in R.AADHAAR_LABELS for w in lower_words):
        logger.debug("[aadhaar_validator] Name rejected (label word): %r", stripped)
        return False

    # Per-word checks
    for word in words:
        if not word:
            continue
        # Trailing punctuation
        if word[-1] in ".,;:!?":
            return False
        # Impossible consonant cluster (garbled Devanagari)
        if R.BAD_CONSONANT_START.match(word):
            logger.debug("[aadhaar_validator] Name rejected (bad consonant): %r in %r", word, stripped)
            return False
        # 4+ letter word with no vowel
        if len(word) >= 4 and not re.search(r"[aeiouAEIOU]", word):
            return False

    # Reject if ALL words are stop words
    if all(w in R.STOP_WORDS for w in lower_words):
        return False

    # Must have at least one word that isn't a stop word
    non_stop = [w for w in lower_words if w not in R.STOP_WORDS]
    if not non_stop:
        return False

    return True
