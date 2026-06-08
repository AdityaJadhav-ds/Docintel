"""
app/parsers/aadhaar/extractor.py — Field extractors with multi-pass voting
==========================================================================
Each extractor:
  1. Receives a list of OCR candidate strings (from multiple regions + variants)
  2. Applies field-specific regex + validation rules
  3. Scores each candidate
  4. Votes across candidates → returns best value + confidence

Fields extracted:
  name, aadhaar_number, dob, gender
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Tuple

from app.core.logger import logger
from . import rules as R
from .validator import (
    validate_aadhaar_number,
    validate_dob,
    validate_gender,
    validate_name,
    normalize_aadhaar,
    normalize_dob,
    normalize_gender,
)


# ─────────────────────────────────────────────────────────────────────────────
# AADHAAR NUMBER
# ─────────────────────────────────────────────────────────────────────────────

def _correct_digits(raw: str) -> str:
    """Apply OCR character→digit substitution."""
    return "".join(R.OCR_DIGIT_MAP.get(c, c) for c in raw)


def _extract_aadhaar_candidates(text: str) -> List[str]:
    """Extract all plausible 12-digit sequences from a text string."""
    candidates = []
    # Strict 4-4-4
    for m in R.AADHAAR_STRICT.finditer(text):
        candidates.append(re.sub(r"[\s\-]", "", m.group(1)))
    # Alt grouping
    for m in R.AADHAAR_ALT.finditer(text):
        raw = re.sub(r"[\s\-]", "", m.group(1))
        if len(raw) == 12:
            candidates.append(raw)
    # Loose: 12-digit line
    for m in R.AADHAAR_LOOSE.finditer(text):
        candidates.append(m.group(1))
    # Correct OCR digits and re-filter
    corrected = []
    for c in candidates:
        fixed = _correct_digits(c)
        if fixed.isdigit() and len(fixed) == 12:
            corrected.append(fixed)
    return corrected


def extract_aadhaar_number(ocr_candidates: List[str]) -> Tuple[Optional[str], float]:
    """
    Vote across all OCR candidate strings for the Aadhaar number.

    Returns:
        (formatted_number, confidence_0_to_1)  or  (None, 0.0)
    """
    all_digits: List[str] = []
    for text in ocr_candidates:
        all_digits.extend(_extract_aadhaar_candidates(text))

    # Filter to valid numbers
    valid = [d for d in all_digits if validate_aadhaar_number(d)]

    if not valid:
        logger.warning("[aadhaar_extractor] No valid Aadhaar number found in %d candidates",
                       len(ocr_candidates))
        return None, 0.0

    # Vote: most common
    counts = Counter(valid)
    winner, vote_count = counts.most_common(1)[0]
    confidence = min(1.0, 0.7 + 0.1 * vote_count + (0.2 if vote_count >= 2 else 0.0))

    formatted = normalize_aadhaar(winner)
    logger.info("[aadhaar_extractor] Aadhaar number: %s (votes=%d conf=%.2f)",
                formatted, vote_count, confidence)
    return formatted, confidence


# ─────────────────────────────────────────────────────────────────────────────
# DATE OF BIRTH
# ─────────────────────────────────────────────────────────────────────────────

def _extract_dob_candidates(text: str) -> List[str]:
    """Extract all plausible DOB strings from a text."""
    candidates = []
    # Label-anchored (highest priority)
    m = R.DOB_LABELLED.search(text)
    if m:
        candidates.append(m.group(1) * 3)  # triple to boost vote weight

    # Full DD/MM/YYYY
    for m in R.DOB_FULL.finditer(text):
        candidates.append(m.group(1))

    # Short year
    for m in R.DOB_SHORT.finditer(text):
        raw = m.group(1)
        # Convert 2-digit year
        parts = re.split(r"[/\-.]", raw)
        if len(parts) == 3:
            yy = int(parts[2])
            full_yr = 2000 + yy if yy <= 25 else 1900 + yy
            candidates.append(f"{parts[0]}/{parts[1]}/{full_yr}")

    # Year-only
    m = R.DOB_YEAR_ONLY.search(text)
    if m:
        candidates.append(m.group(1))

    # Apply digit correction and normalise
    normalised = []
    for c in candidates:
        fixed = _correct_digits(c)
        nd = normalize_dob(fixed)
        if nd:
            normalised.append(nd)
        elif re.fullmatch(r"\d{4}", fixed):
            normalised.append(fixed)
    return normalised


def extract_dob(ocr_candidates: List[str]) -> Tuple[Optional[str], float]:
    """
    Vote across all OCR candidates for the DOB.

    Returns:
        (normalized_dob, confidence_0_to_1)  or  (None, 0.0)
    """
    all_dobs: List[str] = []
    for text in ocr_candidates:
        all_dobs.extend(_extract_dob_candidates(text))

    valid = [d for d in all_dobs if validate_dob(d)]
    if not valid:
        return None, 0.0

    counts = Counter(valid)
    winner, vote_count = counts.most_common(1)[0]
    confidence = min(1.0, 0.6 + 0.15 * vote_count)

    logger.info("[aadhaar_extractor] DOB: %s (votes=%d conf=%.2f)",
                winner, vote_count, confidence)
    return winner, confidence


# ─────────────────────────────────────────────────────────────────────────────
# GENDER
# ─────────────────────────────────────────────────────────────────────────────

_GENDER_NORM = {
    "male": "Male", "mele": "Male", "maie": "Male", "mae": "Male",
    "femal": "Female", "female": "Female", "femafe": "Female",
    "f": "Female", "m": "Male",
}


def extract_gender(ocr_candidates: List[str]) -> Tuple[Optional[str], float]:
    """Scan candidates for Male/Female and return the most voted result."""
    hits: List[str] = []
    for text in ocr_candidates:
        m = R.GENDER_RE.search(text)
        if m:
            raw = m.group(1).lower().strip()
            norm = _GENDER_NORM.get(raw)
            if norm:
                hits.append(norm)

    if not hits:
        return None, 0.0

    counts = Counter(hits)
    winner, vote_count = counts.most_common(1)[0]
    confidence = min(1.0, 0.75 + 0.1 * vote_count)
    logger.info("[aadhaar_extractor] Gender: %s (votes=%d)", winner, vote_count)
    return winner, confidence


# ─────────────────────────────────────────────────────────────────────────────
# NAME
# ─────────────────────────────────────────────────────────────────────────────

# Split line on field-anchor tokens to separate name from trailing data
_NAME_SPLIT_RE = re.compile(
    r"\b(?:dob|date\s+of\s+birth|year\s+of\s+birth|d\.o\.b|male|female|other|"
    r"\d{2}[/\-\.]\d{2}[/\-\.]\d{2,4}|\d{4})\b",
    re.IGNORECASE,
)


def _clean_name_token(token: str) -> str:
    """Strip non-alpha chars and normalize whitespace."""
    cleaned = re.sub(r"[^A-Za-z\s\.\-']", " ", token)
    return re.sub(r"\s+", " ", cleaned).strip()


def _score_name_candidate(candidate: str) -> float:
    """
    Multi-signal scoring:
      + alpha ratio
      + word count (2-4 optimal)
      + title case
      - contains label words
      - single word
      - too long / too short
    """
    stripped = candidate.strip()
    if not stripped:
        return 0.0

    score = 0.0
    words = stripped.split()
    wc = len(words)

    # Alpha ratio
    alpha_r = sum(c.isalpha() for c in stripped) / max(len(stripped), 1)
    score += alpha_r * R.W_ALPHA_RATIO

    # Word count scoring
    if wc == 1:
        score -= 10.0
    elif wc == 2:
        score += R.W_WORD_COUNT_IDEAL * 0.7
    elif 3 <= wc <= 4:
        score += R.W_WORD_COUNT_IDEAL
    elif wc == 5:
        score += R.W_WORD_COUNT_IDEAL * 0.5
    else:
        score -= 15.0

    # Title case
    title_ratio = sum(1 for w in words if w and w[0].isupper()) / max(wc, 1)
    score += title_ratio * R.W_TITLE_CASE

    # Penalty: contains label words
    lower = stripped.lower()
    for label in R.AADHAAR_LABELS:
        if label in lower.split():
            score += R.PENALTY_BLACKLISTED
            break

    # Penalty: noise chars
    noise_r = sum(not c.isalpha() and c not in " .-'" for c in stripped) / max(len(stripped), 1)
    score += noise_r * R.PENALTY_NOISE

    return score


def _split_and_clean_name(line: str) -> List[str]:
    """
    Attempt to extract name parts from a potentially fused OCR line.
    e.g. "Nikita Bhagvan Jadhav DOB: 18/11/2001 Female" → ["Nikita Bhagvan Jadhav"]
    """
    parts = _NAME_SPLIT_RE.split(line)
    results = []
    for part in parts:
        cleaned = _clean_name_token(part)
        if len(cleaned) >= R.NAME_MIN_LEN:
            results.append(cleaned.title())
    return results


def extract_name(
    ocr_candidates: List[str],
    dob_found: Optional[str] = None,
    gender_found: Optional[str] = None,
) -> Tuple[Optional[str], float]:
    """
    Multi-pass name extractor with scoring and voting.

    Strategy:
      1. Each OCR candidate (region text) is split into lines.
      2. Lines are split on DOB/gender anchors to isolate name tokens.
      3. Tokens are scored by field scoring rules.
      4. Top candidate must pass validate_name().
      5. Voting: if the same name appears in multiple OCR passes, confidence boost.

    Returns:
        (name_string, confidence)  or  (None, 0.0)
    """
    scored_candidates: List[Tuple[str, float]] = []
    name_vote_counter: Counter = Counter()

    for text in ocr_candidates:
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if len(line) < R.NAME_MIN_LEN:
                continue
            # Try the line as-is
            candidates_from_line = _split_and_clean_name(line)
            for candidate in candidates_from_line:
                if not validate_name(candidate):
                    continue
                score = _score_name_candidate(candidate)
                if score > 0:
                    scored_candidates.append((candidate, score))
                    name_vote_counter[candidate.lower()] += 1

    if not scored_candidates:
        logger.warning("[aadhaar_extractor] No valid name candidates found")
        return None, 0.0

    # Sort by score descending
    scored_candidates.sort(key=lambda x: x[1], reverse=True)

    # Boost score by vote count
    def boosted(item: Tuple[str, float]) -> float:
        name, sc = item
        votes = name_vote_counter.get(name.lower(), 1)
        return sc + R.W_VOTE_MAJORITY * min(1.0, (votes - 1) * 0.5)

    scored_candidates.sort(key=boosted, reverse=True)

    # Pick the best
    best_name, best_score = scored_candidates[0]
    votes = name_vote_counter.get(best_name.lower(), 1)

    raw_conf = (best_score / (R.W_ALPHA_RATIO + R.W_WORD_COUNT_IDEAL + R.W_TITLE_CASE + R.W_REGION_MATCH))
    confidence = min(1.0, max(0.0, raw_conf + 0.1 * min(votes, 3)))

    logger.info("[aadhaar_extractor] Name: %r (score=%.1f votes=%d conf=%.2f)",
                best_name, best_score, votes, confidence)
    return best_name, confidence
