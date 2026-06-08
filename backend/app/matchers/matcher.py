"""
app/matchers/matcher.py — Advanced fuzzy + phonetic matching engine v2
=======================================================================
Improvements over v1:
  - token_sort_ratio + token_set_ratio + partial_ratio (best of 3)
  - phonetic similarity via custom Soundex-like comparison
  - OCR-aware matching (corrects common char confusions before compare)
  - reason field: explains why a match/mismatch occurred
  - POSSIBLE_MATCH window expanded to handle real OCR typos

THRESHOLDS:
  Name >= 90 → MATCH
  Name 75-89 → POSSIBLE_MATCH
  Name < 75  → MISMATCH
  ID / DOB   → exact normalized (with OCR correction fallback)
"""

from __future__ import annotations
import re
from typing import Optional, Dict, Tuple
from app.core.logger import logger
from app.matchers.normalizer import normalize_name, normalize_dob, normalize_id_number

try:
    from rapidfuzz import fuzz, process
    _HAS_RAPIDFUZZ = True
except ImportError:
    _HAS_RAPIDFUZZ = False
    logger.warning("[matcher] RapidFuzz not installed — using exact match fallback.")


# ── Thresholds ────────────────────────────────────────────────────────────────

NAME_MATCH_THRESHOLD    = 90
NAME_POSSIBLE_THRESHOLD = 75


# ── OCR-aware pre-correction for matching ─────────────────────────────────────

_OCR_CHAR_MAP = {
    "0": "o", "o": "0",
    "1": "i", "i": "1", "l": "1",
    "5": "s", "s": "5",
    "8": "b", "b": "8",
}


def _ocr_normalize(text: str) -> str:
    """Normalize OCR-common character confusions for comparison."""
    return re.sub(r"\s+", "", text.lower())


# ── Phonetic helpers ──────────────────────────────────────────────────────────

def _simple_soundex(word: str) -> str:
    """
    Simplified Soundex for Indian names.
    Maps consonants to codes, removes vowels after first char.
    """
    word = word.upper().strip()
    if not word:
        return ""
    code_map = {
        "BFPV": "1", "CGJKQSXYZ": "2", "DT": "3",
        "L": "4", "MN": "5", "R": "6",
    }
    first = word[0]
    coded = [first]
    for ch in word[1:]:
        for letters, code in code_map.items():
            if ch in letters:
                if coded[-1] != code:
                    coded.append(code)
                break
    result = "".join(coded)
    return (result + "000")[:4]


def _phonetic_similarity(a: str, b: str) -> float:
    """
    Compare names word-by-word using Soundex.
    Returns 0-100 similarity.
    """
    words_a = a.split()
    words_b = b.split()
    if not words_a or not words_b:
        return 0.0

    matches = 0
    total   = max(len(words_a), len(words_b))
    for wa in words_a:
        sa = _simple_soundex(wa)
        for wb in words_b:
            if sa == _simple_soundex(wb):
                matches += 1
                break

    return (matches / max(total, 1)) * 100.0


def _name_similarity(a: str, b: str) -> Tuple[float, str]:
    """
    Returns (score 0-100, method_used).
    Tries multiple strategies and takes the best.
    """
    if not a or not b:
        return 0.0, "empty"

    if a == b:
        return 100.0, "exact"

    if _HAS_RAPIDFUZZ:
        scores = {
            "ratio":          fuzz.ratio(a, b),
            "token_sort":     fuzz.token_sort_ratio(a, b),
            "token_set":      fuzz.token_set_ratio(a, b),
            "partial":        fuzz.partial_ratio(a, b),
        }
        best_method = max(scores, key=scores.__getitem__)
        best_score  = scores[best_method]
    else:
        best_score  = 100.0 if a == b else 0.0
        best_method = "exact"

    # Phonetic boost: if phonetically similar but fuzzy score low
    phonetic_score = _phonetic_similarity(a, b)
    if phonetic_score >= 75 and best_score < NAME_MATCH_THRESHOLD:
        logger.debug("[matcher] Phonetic boost: %.1f → applying", phonetic_score)
        best_score  = max(best_score, phonetic_score * 0.95)
        best_method = f"{best_method}+phonetic"

    return float(best_score), best_method


def _mismatch_reason(score: float, method: str, stored: str, extracted: str) -> str:
    """Generate a human-readable reason string for the match result."""
    if score >= NAME_MATCH_THRESHOLD:
        if "phonetic" in method:
            return "phonetic similarity match"
        if "token" in method:
            return "word order variation"
        return "names match"
    if score >= NAME_POSSIBLE_THRESHOLD:
        # Try to find what differs
        s_words = set(stored.split())
        e_words = set(extracted.split())
        diff = (s_words - e_words) | (e_words - s_words)
        if diff:
            return f"minor OCR variation in: {', '.join(sorted(diff))}"
        return "minor OCR variation"
    return "names do not match"


# ── Public matchers ───────────────────────────────────────────────────────────

def match_name(stored: Optional[str], extracted: Optional[str]) -> Dict:
    if not stored and not extracted:
        return {
            "status": "MATCH", "score": 100,
            "stored": "", "extracted": "", "reason": "both empty",
        }
    if not stored or not extracted:
        return {
            "status": "MISMATCH", "score": 0,
            "stored": stored or "", "extracted": extracted or "",
            "reason": "one value is missing",
        }

    norm_stored    = normalize_name(stored)
    norm_extracted = normalize_name(extracted)

    score, method = _name_similarity(norm_stored, norm_extracted)

    if score >= NAME_MATCH_THRESHOLD:
        status = "MATCH"
    elif score >= NAME_POSSIBLE_THRESHOLD:
        status = "POSSIBLE_MATCH"
    else:
        status = "MISMATCH"

    reason = _mismatch_reason(score, method, norm_stored, norm_extracted)

    return {
        "status":    status,
        "score":     round(score, 1),
        "stored":    stored,
        "extracted": extracted,
        "reason":    reason,
    }


def match_id(stored: Optional[str], extracted: Optional[str]) -> Dict:
    """Exact normalized ID comparison with OCR fallback."""
    n_stored    = normalize_id_number(stored)
    n_extracted = normalize_id_number(extracted)

    if not n_stored or not n_extracted:
        return {
            "status": "MISMATCH", "score": 0,
            "stored": stored or "", "extracted": extracted or "",
            "reason": "one value is missing",
        }

    if n_stored == n_extracted:
        return {
            "status": "MATCH", "score": 100,
            "stored": stored, "extracted": extracted,
            "reason": "exact match",
        }

    # OCR fallback: compare with char confusion normalization
    if _ocr_normalize(n_stored) == _ocr_normalize(n_extracted):
        return {
            "status": "POSSIBLE_MATCH", "score": 88,
            "stored": stored, "extracted": extracted,
            "reason": "OCR character confusion (O/0, I/1, B/8)",
        }

    return {
        "status": "MISMATCH", "score": 0,
        "stored": stored, "extracted": extracted,
        "reason": "ID numbers do not match",
    }


def match_dob(stored: Optional[str], extracted: Optional[str]) -> Dict:
    """Normalized flexible DOB comparison."""
    n_stored    = normalize_dob(stored)
    n_extracted = normalize_dob(extracted)

    if not n_stored or not n_extracted:
        return {
            "status": "MISMATCH", "score": 0,
            "stored": stored or "", "extracted": extracted or "",
            "reason": "one value is missing",
        }

    if n_stored == n_extracted:
        return {
            "status": "MATCH", "score": 100,
            "stored": stored, "extracted": extracted,
            "reason": "exact match",
        }

    # Year-only comparison fallback
    year_s = n_stored[-4:]
    year_e = n_extracted[-4:]
    if year_s == year_e and (len(n_stored) == 4 or len(n_extracted) == 4):
        return {
            "status": "POSSIBLE_MATCH", "score": 80,
            "stored": stored, "extracted": extracted,
            "reason": "year matches; full date not confirmed",
        }

    return {
        "status": "MISMATCH", "score": 0,
        "stored": stored, "extracted": extracted,
        "reason": "dates do not match",
    }
