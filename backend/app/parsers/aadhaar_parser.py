"""
app/parsers/aadhaar_parser.py — Production-grade Aadhaar field extractor v3
============================================================================
v3: Multi-variant DOB voting, enhanced date correction, improved name ranking.

PASSES:
  Pass 1 — Direct regex on cleaned text
  Pass 2 — OCR-corrected candidates
  Pass 3 — Numeric-only line scan (Aadhaar fallback)

VOTING:
  - DOB: collect candidates from ALL OCR variants and vote by frequency
  - Aadhaar number: similarly voted across variants

Returns per-field confidence scores (0-100).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Optional, Dict, List, Tuple
from app.core.logger import logger
from app.ocr.text_cleaner import clean_ocr_text, clean_field_value
from app.ocr.correction_engine import correct_aadhaar_candidate, find_corrected_aadhaar, find_corrected_date
from app.ocr.confidence_engine import calculate_field_confidence
from app.utils.blacklists import is_aadhaar_blacklisted
from app.parsers.field_ranker import best_name_candidate, rank_name_candidates


# ── Regex patterns ─────────────────────────────────────────────────────────────

# Strict: proper 12-digit Aadhaar (space or dash separated groups)
_AADHAAR_STRICT = re.compile(r"\b(\d{4}[\s\-]\d{4}[\s\-]\d{4})\b")
# Alternative grouping: 8+4 or 4+8 (OCR spacing issues)
_AADHAAR_ALT    = re.compile(r"\b(\d{4}[\s\-]\d{8}|\d{8}[\s\-]\d{4})\b")
# Loose: digits possibly without spaces — MUST be on a line with ONLY digits/spaces
# (prevent year+Aadhaar concatenation matches)
_AADHAAR_LOOSE  = re.compile(r"^[\s]*?(\d{12})[\s]*?$", re.MULTILINE)

# DOB patterns — ordered by specificity
_DOB_PATTERNS = [
    # With explicit DOB label
    re.compile(r"(?:DOB|Date\s+of\s+Birth|D\.O\.B)[^\d]*(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})", re.IGNORECASE),
    # Standard DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    re.compile(r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})\b"),
    # Year of Birth label
    re.compile(r"(?:Year\s+of\s+Birth|YOB)[^\d]*(\d{4})", re.IGNORECASE),
    # DD/MM/YY (short year)
    re.compile(r"\b(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{2})\b"),
]

# Anchor keywords for positional analysis
_AADHAAR_ANCHORS = [
    "government of india",
    "govt of india",
    "uidai",
    "aadhaar",
    "dob",
    "male",
    "female",
    "date of birth",
    "year of birth",
]

# Date correction map: char that might appear in digit positions
_DATE_CORRECTION_MAP = {
    "l": "1", "I": "1", "i": "1",
    "O": "0", "o": "0",
    "S": "5", "s": "5",
    "Z": "2", "z": "2",
    "B": "8",   # KEY FIX: B → 8 (handles 19 vs 18 confusion when OCR reads 8 as B or 9)
    "g": "9",   # common OCR confusion: g → 9
    "q": "9",   # q → 9
}


# ── Date correction (enhanced) ──────────────────────────────────────────────────

def _correct_date_string(raw: str) -> Optional[str]:
    """
    Apply character correction to a date string.
    Handles: l/I → 1, O/o → 0, S → 5, Z → 2, B → 8
    """
    corrected = ""
    for ch in raw:
        corrected += _DATE_CORRECTION_MAP.get(ch, ch)
    m = re.fullmatch(r"(\d{2})[\/\-\.](\d{2})[\/\-\.](\d{4})", corrected)
    if m:
        day, month, year = m.group(1), m.group(2), m.group(3)
        # Validate realistic date ranges
        try:
            d, mo, y = int(day), int(month), int(year)
            if 1 <= d <= 31 and 1 <= mo <= 12 and 1900 <= y <= 2025:
                return f"{day}/{month}/{year}"
        except ValueError:
            pass
    return None


def _normalize_date(raw: str) -> Optional[str]:
    """Normalize a raw date match to DD/MM/YYYY."""
    raw = raw.strip()
    # Try correction first
    corrected = _correct_date_string(raw)
    if corrected:
        return corrected
    # Simple normalization
    m = re.fullmatch(r"(\d{2})[\/\-\.](\d{2})[\/\-\.](\d{4})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    # 2-digit year
    m = re.fullmatch(r"(\d{2})[\/\-\.](\d{2})[\/\-\.](\d{2})", raw)
    if m:
        year = int(m.group(3))
        full_year = 2000 + year if year <= 25 else 1900 + year
        return f"{m.group(1)}/{m.group(2)}/{full_year}"
    return None


# ── Pass 1: Direct regex ───────────────────────────────────────────────────────

def _is_valid_aadhaar(aadhaar: str) -> bool:
    """
    Basic sanity check: first group must NOT look like a year (1800-2099)
    and second group must NOT look like a date month (01-12 padded to 4 digits).
    """
    digits = re.sub(r"\s+", "", aadhaar)
    if len(digits) != 12:
        return False
    first4 = int(digits[:4])
    # Reject if first 4 digits look like a year
    if 1800 <= first4 <= 2099:
        return False
    # All-zero groups are invalid
    if digits[:4] == "0000" or digits[4:8] == "0000" or digits[8:] == "0000":
        return False
    return True


def _extract_aadhaar_pass1(text: str) -> Optional[str]:
    """Strict regex + loose 12-digit scan with validity check."""
    m = _AADHAAR_STRICT.search(text)
    if m:
        raw = re.sub(r"[\s\-]", "", m.group(1))
        candidate = f"{raw[:4]} {raw[4:8]} {raw[8:]}"
        if _is_valid_aadhaar(candidate):
            return candidate
    m = _AADHAAR_ALT.search(text)
    if m:
        raw = re.sub(r"[\s\-]", "", m.group(1))
        if len(raw) == 12:
            candidate = f"{raw[:4]} {raw[4:8]} {raw[8:]}"
            if _is_valid_aadhaar(candidate):
                return candidate
    m = _AADHAAR_LOOSE.search(text)
    if m:
        d = m.group(1)
        candidate = f"{d[:4]} {d[4:8]} {d[8:]}"
        if _is_valid_aadhaar(candidate):
            return candidate
    return None


def _extract_dob_from_text(text: str) -> Optional[str]:
    """
    Try all DOB patterns and return the first valid, corrected date.
    Prioritizes DOB-label-anchored matches.
    """
    # First: try label-anchored pattern (most reliable)
    m = _DOB_PATTERNS[0].search(text)
    if m:
        normalized = _normalize_date(m.group(1))
        if normalized:
            return normalized

    # Second: try standard date pattern
    for m in _DOB_PATTERNS[1].finditer(text):
        normalized = _normalize_date(m.group(1))
        if normalized:
            return normalized

    # Third: year-only
    m = _DOB_PATTERNS[2].search(text)
    if m:
        return m.group(1)

    # Fourth: short year
    for m in _DOB_PATTERNS[3].finditer(text):
        normalized = _normalize_date(m.group(1))
        if normalized:
            return normalized

    return None


# ── Pass 2: OCR-corrected ──────────────────────────────────────────────────────

def _extract_aadhaar_pass2(text: str) -> Optional[str]:
    return find_corrected_aadhaar(text)


def _extract_dob_pass2(text: str) -> Optional[str]:
    return find_corrected_date(text)


# ── Pass 3: Numeric-line scan ──────────────────────────────────────────────────

def _extract_aadhaar_pass3(lines: List[str]) -> Optional[str]:
    """
    Find lines that are predominantly numeric and could be Aadhaar.
    e.g. "5395 8342 1089" isolated on a line.
    """
    for line in lines:
        stripped = line.strip()
        digits = re.sub(r"[\s\-]", "", stripped)
        if digits.isdigit() and len(digits) == 12:
            candidate = f"{digits[:4]} {digits[4:8]} {digits[8:]}"
            if _is_valid_aadhaar(candidate):
                return candidate
    return None


# ── Multi-variant voting ───────────────────────────────────────────────────────

def _vote_dob(candidates: List[Optional[str]]) -> Optional[str]:
    """
    Pick the best DOB by majority vote across all OCR variants.
    Normalize dates for comparison, return the most common valid one.
    """
    valid: List[str] = []
    for c in candidates:
        if not c:
            continue
        normalized = _normalize_date(c) if not re.fullmatch(r"\d{4}", c) else c
        if normalized:
            valid.append(normalized)

    if not valid:
        return None

    counts = Counter(valid)
    logger.debug("[aadhaar_parser] DOB vote counts: %s", dict(counts))
    winner = counts.most_common(1)[0][0]
    return winner


def _vote_aadhaar(candidates: List[Optional[str]]) -> Optional[str]:
    """Pick the most common VALID Aadhaar number across OCR variants."""
    # Filter: must pass validity check (no year-prefix, no zeros)
    valid = [c for c in candidates if c and _is_valid_aadhaar(c)]
    if not valid:
        # If all filtered out, return unfiltered most-common as last resort
        valid = [c for c in candidates if c]
        if not valid:
            return None
    # Normalize (remove spaces for comparison)
    norm = [re.sub(r"\s+", "", v) for v in valid]
    counts = Counter(norm)
    winner_norm = counts.most_common(1)[0][0]
    # Return properly formatted version
    for original, n in zip(valid, norm):
        if n == winner_norm:
            return original
    return valid[0]


# ── Name extraction ─────────────────────────────────────────────────────────────

def _find_anchor_line_idxs(lines: List[str]) -> List[int]:
    """Return indices of lines containing anchor keywords."""
    idxs = []
    for i, line in enumerate(lines):
        lower = line.lower()
        if any(kw in lower for kw in _AADHAAR_ANCHORS):
            idxs.append(i)
    return idxs


def _find_goi_line_idx(lines: List[str]) -> Optional[int]:
    """
    Find the 'Government of India' header line — acts as the UPPER boundary
    of the name zone. Name always appears BELOW this line on the Aadhaar card.
    """
    goi_keywords = [
        "government of india",
        "govt of india",
        "uidai",
        "unique identification authority",
    ]
    for i, line in enumerate(lines):
        lower = line.lower().strip()
        if any(kw in lower for kw in goi_keywords):
            return i
    return None


def _find_dob_line_idx(lines: List[str]) -> Optional[int]:
    """Find the line index where DOB appears — used as proximity anchor for name."""
    for i, line in enumerate(lines):
        if _extract_dob_from_text(line):
            return i
        if re.search(r"\bdob\b|\bdate\s+of\s+birth\b|\byear\s+of\s+birth\b", line, re.IGNORECASE):
            return i
    return None


# Address/location noise patterns — must not be extracted as name
_ADDRESS_WORDS = re.compile(
    r"\b(village|dist|district|state|pin|post|tehsil|mandal|taluk|taluka|"
    r"near|landmark|ward|nagar|colony|sector|block|road|street|mohalla|"
    r"flat|house|plot|s/o|d/o|w/o|c/o|at|po|ps|via)\b",
    re.IGNORECASE,
)

# ── Devanagari-garble detection ─────────────────────────────────────────────
# When Tesseract reads Hindi/Devanagari script with lang=eng, it produces
# garbage English-looking strings like "Gni Nao To Any." — these look valid
# (title case, 3-4 words, no digits) but fail word-level plausibility checks.

# Consonant clusters that NEVER start a valid English or Indian name in English
_INVALID_NAME_STARTS = re.compile(
    r"^(gn|mn|dn|tn|rn|fn|vn|bn|pn|ng|nr|nl|nk|wr(?!i)|"   # impossible combos
    r"ch(?![aeiouAEIOU])|gh(?![aeiouAEIOU])|[bcdfghjklmnpqrstvwxyz]{3})",  # 3+ consonants
    re.IGNORECASE,
)

# Common English function/stop words that are not names, but short enough to
# appear as a standalone "word" inside garbled OCR output
_ENGLISH_NON_NAMES: set = {
    "to", "of", "in", "by", "an", "at", "on", "or", "as", "is", "it",
    "if", "no", "up", "do", "go", "so", "us", "we", "he", "me", "my",
    "any", "the", "and", "for", "not", "but", "can", "was", "are",
    "did", "had", "has", "may", "too", "see", "get", "use", "say",
    "put", "end", "did", "his", "her", "him", "she", "our", "its",
    "now", "new", "old", "big", "all", "one", "two", "yes", "yet",
    "also", "well", "than", "with", "this", "that", "they", "from",
    "have", "been", "what", "when", "your", "some", "just", "will",
    "more", "very", "much", "only", "even", "both", "such", "then",
    "into", "over", "back", "here", "made", "take", "time", "like",
    "good", "know", "look", "make", "come", "give", "most", "need",
    "also", "else", "away", "down", "each", "many", "next", "same",
    "said", "once", "tell", "want", "well", "went", "were", "whom",
}

# Valid 2-character name fragments (initials, prefixes, short names)
# Everything else at 2-chars is likely garble ("Jo", "Wa", "Re", "Ya" etc.)
_VALID_2CHAR_NAMES: set = {
    "al", "el", "de", "du", "la", "le", "mc", "st", "da", "di",
    "do", "ma", "ra", "sa", "ka", "ta", "na", "pa", "va", "ba",
    "om", "sk", "rk", "ak", "pk", "ed", "ad", "bo",
}


def _word_is_plausible_name_token(word: str) -> bool:
    """
    Return True if `word` could be part of a proper Indian/English name.

    Rejects:
      - Words ending with punctuation (OCR garble artifact: "Any.")
      - Words with impossible consonant-cluster starts (garbled Devanagari: "Gni")
      - 4+ letter words with no vowel (not possible in English names)
      - Common English stop-words used as standalone name tokens ("To", "Any")

    Allows:
      - Single-letter initials ("A", "B")
      - 2-3 letter name fragments ("Mc", "O'", "Al")
      - All valid Indian names in English spelling
    """
    if not word:
        return False
    # Strip trailing punctuation for check purposes (e.g. "Any.")
    if word[-1] in ".,;:!?":
        return False
    w_lower = word.lower()
    # Single-letter initial — always allow
    if len(word) == 1:
        return word.isalpha()
    # Impossible consonant cluster start (garbled Devanagari pattern)
    if _INVALID_NAME_STARTS.match(word):
        logger.debug("[aadhaar_parser] Rejected word %r (bad consonant cluster)", word)
        return False
    # 4+ letter word with no vowel → not a valid name word
    if len(word) >= 4 and not re.search(r"[aeiouAEIOU]", word):
        return False
    # Common English stop/function words are not names
    if w_lower in _ENGLISH_NON_NAMES:
        logger.debug("[aadhaar_parser] Rejected word %r (English stop word)", word)
        return False
    # 2-letter words: only allow known valid short Indian name tokens
    # (single-letter initials already handled above)
    # 2-char garble fragments like "Wa", "Jo", "Re", "Ya" are rejected
    # unless they're in the allowed list of valid short name components
    if len(word) == 2 and w_lower not in _VALID_2CHAR_NAMES:
        logger.debug("[aadhaar_parser] Rejected 2-char word %r (not a valid name fragment)", word)
        return False
    return True


def _is_human_name(candidate: str) -> bool:
    """
    Validate that a candidate string looks like a human name.

    Checks (in order):
      1. Character set: alpha + spaces + dots/hyphens/apostrophes only
      2. Length: 4-50 chars total
      3. Word count: 1-5 words
      4. Single-letter initials must be alpha
      5. No address/location keywords
      6. Word-level plausibility: each word must pass _word_is_plausible_name_token
         (this filters garbled Devanagari like "Gni Nao To Any.")
    """
    stripped = candidate.strip()
    # Length gate
    if len(stripped) < 4 or len(stripped) > 50:
        return False
    # Only allow alpha + spaces + basic punctuation (dots, hyphens, apostrophes)
    if not re.fullmatch(r"[A-Za-z\s\.\-']+", stripped):
        return False
    words = stripped.split()
    # Word count
    if len(words) < 1 or len(words) > 5:
        return False
    # Each word must be at least 2 chars, EXCEPT single-letter initials
    if any(len(w) == 1 and not w.isalpha() for w in words):
        return False
    # No address words
    if _ADDRESS_WORDS.search(stripped):
        return False
    # ── Word-level plausibility (catches garbled Devanagari) ─────────────────
    for w in words:
        if not _word_is_plausible_name_token(w):
            logger.debug(
                "[aadhaar_parser] _is_human_name rejected %r — word %r failed plausibility",
                stripped, w
            )
            return False
    return True


# Minimum score a name candidate must achieve to be accepted
_MIN_NAME_SCORE = 18.0


def _try_name_from_fused_line(line: str) -> Optional[str]:
    """
    Image OCR often fuses name + DOB onto one line, e.g.:
      'Aditya Bhagavan Jadhav DOB: 01/01/1990'
      'RAMESH KUMAR Male 25/06/1985'
    Split on known Aadhaar field labels and try to extract the name part.
    """
    from app.ocr.correction_engine import correct_name_text
    # Split on DOB / gender keywords
    split_pattern = re.compile(
        r"\b(?:dob|date\s+of\s+birth|year\s+of\s+birth|d\.o\.b|male|female|other|"
        r"\d{2}[/\-.:]\d{2}[/\-.:]\d{2,4}|\d{4})\b",
        re.IGNORECASE,
    )
    parts = split_pattern.split(line)
    for part in parts:
        part = part.strip()
        if len(part) < 4:
            continue
        # Strip non-alpha
        english = re.sub(r"[^A-Za-z\s.\-']", " ", part)
        english = re.sub(r"\s+", " ", english).strip()
        candidate = english.title()
        cleaned = correct_name_text(candidate)
        if cleaned and _is_human_name(cleaned.title()):
            return cleaned.title()
    return None


def _extract_name_from_region_ocr(image_gray) -> Optional[str]:
    """
    Fallback: crop the Aadhaar name region (top 15-55%) and re-run targeted
    OCR with multiple PSM modes. Useful when full-image OCR merges lines.
    """
    try:
        import cv2
        import numpy as np
        from app.ocr.region_ocr import _preprocess_region, _run_tess, _crop_aadhaar_name_region
        from app.ocr.correction_engine import correct_name_text

        gray = cv2.cvtColor(image_gray, cv2.COLOR_BGR2GRAY) if len(image_gray.shape) == 3 else image_gray
        name_crop = _crop_aadhaar_name_region(gray)
        processed = _preprocess_region(name_crop)

        for psm in [4, 6, 11, 7]:
            text = _run_tess(processed, psm=psm)
            if not text:
                continue
            region_lines = [l.strip() for l in text.splitlines() if l.strip()]
            logger.debug("[aadhaar_parser] Region OCR psm=%d lines=%s", psm, region_lines[:5])

            # Find anchors relative to this cropped region
            region_anchor_idxs = [
                i for i, ln in enumerate(region_lines)
                if any(kw in ln.lower() for kw in _AADHAAR_ANCHORS)
            ]

            ranked = rank_name_candidates(region_lines, region_anchor_idxs, is_aadhaar_blacklisted,
                                          name_zone_range=(0, len(region_lines)))
            for candidate, score in ranked:
                if score < _MIN_NAME_SCORE:
                    break
                cleaned = correct_name_text(candidate)
                if not cleaned:
                    continue
                english = re.sub(r"[^A-Za-z\s.\-']", " ", cleaned)
                english = re.sub(r"\s+", " ", english).strip()
                result = english.title()
                if _is_human_name(result):
                    logger.info("[aadhaar_parser] Region OCR name: %r (psm=%d score=%.1f)",
                                result, psm, score)
                    return result

            # Also try fused-line splitting on region text
            for ln in region_lines:
                if len(ln) > 20:
                    extracted = _try_name_from_fused_line(ln)
                    if extracted:
                        logger.info("[aadhaar_parser] Region OCR fused-line name: %r", extracted)
                        return extracted

    except Exception as exc:
        logger.warning("[aadhaar_parser] Region OCR fallback failed: %s", exc)
    return None


def _extract_name(lines: List[str], image_gray=None) -> Optional[str]:
    """
    Multi-signal name extraction — v5 (image-aware).

    Key improvements over v4:
      1. GOI → DOB zone: name is in the band between 'Government of India'
         and the DOB line.  This is the tightest, most reliable zone.
      2. Fused-line splitting: image OCR often merges 'Name DOB Gender' onto
         one long line; we split on field-label tokens before scoring.
      3. Minimum score gate: candidates below _MIN_NAME_SCORE are rejected
         to prevent low-confidence garbage from being returned.
      4. Region-crop fallback: if all text passes fail, crop the upper card
         region and re-run OCR with PSM modes tuned for single lines.
      5. Full debug logging of all candidates, scores, and zone.
    """
    from app.ocr.correction_engine import correct_name_text

    goi_idx    = _find_goi_line_idx(lines)
    dob_idx    = _find_dob_line_idx(lines)
    anchor_idxs = _find_anchor_line_idxs(lines)

    logger.debug(
        "[aadhaar_parser] _extract_name: total_lines=%d goi_idx=%s dob_idx=%s",
        len(lines), goi_idx, dob_idx
    )

    # ── Define search zone ────────────────────────────────────────────────────
    if goi_idx is not None and dob_idx is not None and dob_idx > goi_idx:
        # PRIMARY zone: strictly between GOI header and DOB line
        start_idx = goi_idx + 1
        end_idx   = dob_idx          # exclusive — don't include DOB line itself
        zone_label = "goi_to_dob"
    elif dob_idx is not None:
        # No GOI found (photo crop or poor OCR): search from start up to DOB
        start_idx = 0
        end_idx   = min(dob_idx + 1, len(lines))
        zone_label = "start_to_dob"
    else:
        # No anchors at all: search first 80% of lines
        start_idx = 0
        end_idx   = max(1, int(len(lines) * 0.8))
        zone_label = "first_80pct"

    start_idx = max(0, start_idx)
    end_idx   = min(len(lines), end_idx)

    logger.debug(
        "[aadhaar_parser] Name search zone: lines[%d:%d] (%s)",
        start_idx, end_idx, zone_label
    )

    search_lines = lines[start_idx:end_idx]

    # Adjust anchor indices to the sliced window
    rel_anchors = [a - start_idx for a in anchor_idxs if start_idx <= a < end_idx]

    # ── If the primary zone is empty, relax to pre-DOB ───────────────────────
    if not search_lines and dob_idx is not None:
        logger.debug("[aadhaar_parser] Primary zone empty — relaxing to start_to_dob")
        start_idx   = 0
        end_idx     = min(dob_idx + 2, len(lines))
        search_lines = lines[start_idx:end_idx]
        rel_anchors  = [a for a in anchor_idxs if a < end_idx]
        zone_label   = "start_to_dob_relaxed"

    # ── Score candidates in the zone ─────────────────────────────────────────
    # Pass the full range so every line in search_lines gets the zone bonus
    zone_range = (0, len(search_lines))
    ranked = rank_name_candidates(search_lines, rel_anchors, is_aadhaar_blacklisted,
                                  name_zone_range=zone_range)

    logger.debug(
        "[aadhaar_parser] Name candidates (zone=%s, count=%d): %s",
        zone_label, len(ranked),
        [(r[0], round(r[1], 1)) for r in ranked[:8]]
    )

    # ── Pass A: scored candidates above threshold ─────────────────────────────
    for candidate, score in ranked:
        if score < _MIN_NAME_SCORE:
            logger.debug(
                "[aadhaar_parser] Score %.1f below threshold %.1f — stopping candidate scan",
                score, _MIN_NAME_SCORE
            )
            break
        cleaned = correct_name_text(candidate)
        if not cleaned:
            continue
        english = re.sub(r"[^A-Za-z\s.\-']", " ", cleaned)
        english = re.sub(r"\s+", " ", english).strip()
        result  = english.title()
        if _is_human_name(result):
            logger.info(
                "[aadhaar_parser] [PASS-A] Name accepted: %r (score=%.1f zone=%s)",
                result, score, zone_label
            )
            return result
        logger.debug("[aadhaar_parser] Name rejected (human-name check): %r score=%.1f", result, score)

    # ── Pass B: fused-line splitting ──────────────────────────────────────────
    # Try lines in the search zone that are too long to score well individually
    logger.debug("[aadhaar_parser] Pass-B: trying fused-line splitting on %d lines", len(search_lines))
    for ln in search_lines:
        if len(ln.strip()) > 20:
            fused = _try_name_from_fused_line(ln)
            if fused:
                logger.info("[aadhaar_parser] [PASS-B] Fused-line name: %r", fused)
                return fused

    # Also try the DOB line itself (name and DOB sometimes on same line)
    if dob_idx is not None and 0 <= dob_idx < len(lines):
        dob_line = lines[dob_idx]
        if len(dob_line.strip()) > 10:
            fused = _try_name_from_fused_line(dob_line)
            if fused:
                logger.info("[aadhaar_parser] [PASS-B] Fused-line name from DOB line: %r", fused)
                return fused

    # ── Pass C: region OCR fallback (only for image uploads) ─────────────────
    if image_gray is not None:
        logger.info("[aadhaar_parser] Pass-C: attempting region OCR fallback")
        region_name = _extract_name_from_region_ocr(image_gray)
        if region_name:
            return region_name

    logger.warning(
        "[aadhaar_parser] All name extraction passes failed (zone=%s candidates=%d)",
        zone_label, len(ranked)
    )
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_aadhaar(
    ocr_text: str,
    variant_texts: Optional[Dict[str, str]] = None,
    image_gray=None,   # optional np.ndarray for region OCR
) -> Dict:
    """
    Production-grade Aadhaar parser v3 with multi-variant voting.

    Returns:
        {
            "name":             str | None,
            "aadhaar_number":   str | None,
            "dob":              str | None,
            "confidence":       float (0-1),
            "field_confidences": {...},
            "debug": {...}
        }
    """
    if not ocr_text or not ocr_text.strip():
        return {
            "name": None, "aadhaar_number": None, "dob": None,
            "confidence": 0.0,
            "field_confidences": {"name": 0, "aadhaar_number": 0, "dob": 0},
            "debug": {"method": "empty_input"},
        }

    # ── Step 1: Clean text ────────────────────────────────────────────────────
    clean_text = clean_ocr_text(ocr_text, doc_type="aadhaar")
    lines      = clean_text.splitlines()
    vt         = variant_texts or {}

    logger.debug("[aadhaar_parser] Cleaned text (%d lines):\n%s", len(lines), clean_text[:500])

    # ── Step 2: Multi-pass + multi-variant Aadhaar number ────────────────────
    aadhaar_candidates: List[Optional[str]] = [
        _extract_aadhaar_pass1(clean_text),
        _extract_aadhaar_pass2(clean_text),
        _extract_aadhaar_pass3(lines),
    ]
    for v_text in vt.values():
        if v_text:
            v_clean = clean_ocr_text(v_text, doc_type="aadhaar")
            v_lines = v_clean.splitlines()
            aadhaar_candidates.append(_extract_aadhaar_pass1(v_clean))
            aadhaar_candidates.append(_extract_aadhaar_pass2(v_clean))
            aadhaar_candidates.append(_extract_aadhaar_pass3(v_lines))

    aadhaar_number = _vote_aadhaar(aadhaar_candidates)
    logger.info("[aadhaar_parser] Aadhaar candidates=%s -> winner=%s",
                [c for c in aadhaar_candidates if c], aadhaar_number)

    # -- Step 3: Multi-variant DOB voting -------------------------------------
    # Collect ONE candidate per source to prevent double-counting.
    dob_candidates: List[Optional[str]] = []

    # Main OCR text: pick its best DOB (label-anchored wins over bare match)
    main_dob = _extract_dob_from_text(clean_text) or _extract_dob_pass2(clean_text)
    if main_dob:
        dob_candidates.append(main_dob)

    # One candidate per variant
    for v_name, v_text in vt.items():
        if not v_text:
            continue
        v_clean = clean_ocr_text(v_text, doc_type="aadhaar")
        candidate = _extract_dob_from_text(v_clean) or _extract_dob_pass2(v_clean)
        if candidate:
            dob_candidates.append(candidate)
            logger.debug("[aadhaar_parser] DOB from variant %r: %s", v_name, candidate)

    dob = _vote_dob(dob_candidates)
    logger.info("[aadhaar_parser] DOB candidates=%s -> winner=%s",
                [c for c in dob_candidates if c], dob)

    # ── Step 4: Name extraction ───────────────────────────────────────────────
    # Pass image_gray so the region-OCR fallback is available for images.
    # (image_gray is None for PDF/direct-text paths — fallback is skipped gracefully)
    name = _extract_name(lines, image_gray=image_gray)
    # Try from variant texts if not found
    if name is None:
        for v_name, v_text in vt.items():
            if not v_text:
                continue
            v_clean = clean_ocr_text(v_text, doc_type="aadhaar")
            v_lines = v_clean.splitlines()
            name_candidate = _extract_name(v_lines)
            if name_candidate:
                logger.info("[aadhaar_parser] Name found in variant %r: %r", v_name, name_candidate)
                name = name_candidate
                break

    if aadhaar_number:
        logger.info("[aadhaar_parser] [OK] Aadhaar: %s", aadhaar_number)
    else:
        logger.warning("[aadhaar_parser] [MISS] Aadhaar NOT found")
        logger.debug("[aadhaar_parser] Text sample: %s", clean_text[:300].replace("\n", " | "))

    if dob:
        logger.info("[aadhaar_parser] [OK] DOB: %s", dob)
    else:
        logger.warning("[aadhaar_parser] [MISS] DOB NOT found")

    if name:
        logger.info("[aadhaar_parser] [OK] Name: %s", name)
    else:
        logger.warning("[aadhaar_parser] [MISS] Name NOT found")

    # ── Step 5: Confidence scoring ────────────────────────────────────────────
    fc = {
        "aadhaar_number": calculate_field_confidence("aadhaar_number", aadhaar_number, clean_text, vt),
        "dob":            calculate_field_confidence("dob",            dob,            clean_text, vt),
        "name":           calculate_field_confidence("name",           name,           clean_text, vt),
    }

    found = sum([name is not None, aadhaar_number is not None, dob is not None])
    overall_confidence = round(
        (fc["aadhaar_number"] + fc["dob"] + fc["name"]) / 300.0, 4
    ) if found else 0.0

    return {
        "name":              name,
        "aadhaar_number":    aadhaar_number,
        "dob":               dob,
        "confidence":        overall_confidence,
        "field_confidences": fc,
        "debug": {
            "aadhaar_candidates": [c for c in aadhaar_candidates if c],
            "dob_candidates":     [c for c in dob_candidates if c],
            "lines_count":        len(lines),
            "has_image_gray":     image_gray is not None,
        },
    }
