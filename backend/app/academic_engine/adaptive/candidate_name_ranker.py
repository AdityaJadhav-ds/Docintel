"""
academic_engine/adaptive/candidate_name_ranker.py
===================================================
Candidate Name Extraction and Ranking Engine.

The problem: OCR on the candidate block produces multiple text tokens.
Some are the actual name, many are noise (labels, codes, dates, IDs).

Ranking rules (scored 0–100):
  +30  exactly 2–5 words
  +20  all words alphabetic (no digits/symbols)
  +15  title-case (e.g., "Rahul Sharma")
  +15  no academic/noise keywords
  +10  word lengths reasonable (2–20 chars each)
  +10  centered horizontally in the zone (if bbox available)
  -30  contains digits
  -20  single word only
  -20  more than 6 words
  -15  contains known noise words
  -10  all uppercase AND length > 20 chars

Output:
  best name string or None
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.core.logger import logger

# ── Noise word sets ────────────────────────────────────────────────────────────

ACADEMIC_NOISE = {
    "board", "university", "college", "institute", "school",
    "marksheet", "certificate", "examination", "result", "class",
    "roll", "seat", "prn", "enrol", "index", "reg", "register",
    "mother", "father", "guardian", "address", "date", "birth",
    "standard", "stream", "division", "medium", "year", "session",
    "subject", "marks", "total", "percentage", "grade", "pass", "fail",
    "sr", "no", "number", "form",
    # Common marksheet header words that score highly by mistake
    "secondary", "higher", "statement", "hsc", "ssc", "cbse", "icse",
    "maharashtra", "board", "pune", "nagpur", "mumbai", "kolhapur",
    "education", "science", "arts", "commerce",
}

# Patterns that disqualify a candidate
_HAS_DIGIT = re.compile(r'\d')
_HAS_SYMBOL = re.compile(r'[^A-Za-z\s\.\-]')
_TITLE_CASE = re.compile(r'^[A-Z][a-z]+(\s[A-Z][a-z]+)+$')
_ALL_CAPS   = re.compile(r'^[A-Z\s]+$')


@dataclass
class NameCandidate:
    text:      str
    score:     float
    bbox:      Optional[tuple] = None    # (x, y, w, h) or None

    def __repr__(self) -> str:
        return f"NameCandidate({self.text!r}, score={self.score:.1f})"


def _score_candidate(text: str, zone_width: int = 0, bbox=None) -> float:
    """
    Score a raw text string as a name candidate.
    Returns float score (higher = more likely a valid name).
    """
    score = 0.0
    words = text.strip().split()

    if not words:
        return -100.0

    # Word count
    n = len(words)
    if 2 <= n <= 4:
        score += 30
    elif n == 5:
        score += 20
    elif n == 1:
        score -= 20
    elif n > 5:
        score -= 20 + (n - 5) * 5

    # All alphabetic words
    if all(re.fullmatch(r'[A-Za-z\.\-]+', w) for w in words):
        score += 20
    else:
        score -= 30

    # No digits
    if _HAS_DIGIT.search(text):
        score -= 30

    # No symbols
    if _HAS_SYMBOL.search(text):
        score -= 15

    # Title case
    if _TITLE_CASE.match(text.strip()):
        score += 15

    # No noise keywords
    text_lower = text.lower()
    noise_hits = sum(1 for nw in ACADEMIC_NOISE if nw in text_lower.split())
    if noise_hits == 0:
        score += 15
    else:
        score -= 15 * noise_hits

    # Reasonable word lengths
    if all(2 <= len(w) <= 20 for w in words):
        score += 10

    # Centered heuristic (if we have bbox and zone width)
    if bbox is not None and zone_width > 50:
        x, _, w, _ = bbox
        center_x = x + w / 2
        dist_from_center = abs(center_x - zone_width / 2) / (zone_width / 2)
        if dist_from_center < 0.25:
            score += 10
        elif dist_from_center > 0.6:
            score -= 5

    # Long all-caps penalty
    if _ALL_CAPS.match(text.strip()) and len(text) > 20:
        score -= 10

    return score


def rank_name_candidates(
    word_records: List[Dict],       # {text, bbox, conf} from Tesseract
    zone_width:   int = 0,
    min_score:    float = 20.0,
) -> Optional[str]:
    """
    Given a list of word records from OCR of the candidate zone,
    rank and return the best name candidate.

    Args:
        word_records: List of word dicts from Tesseract image_to_data.
        zone_width:   Width of the zone image (for centering heuristic).
        min_score:    Minimum score to accept a candidate.

    Returns:
        Best name string (title-cased) or None.
    """
    if not word_records:
        return None

    # Group words into row clusters
    from app.academic_engine.layout_v2.spatial_relationships import group_into_rows
    bboxes = [w["bbox"] for w in word_records]
    rows   = group_into_rows(bboxes, row_gap_px=18)

    candidates: List[NameCandidate] = []

    for row_bboxes in rows:
        # Reconstruct words for this row
        row_words = []
        for bbox in row_bboxes:
            for w in word_records:
                if w["bbox"] == bbox:
                    row_words.append(w)
                    break

        if not row_words:
            continue

        # Try full row
        full_text = " ".join(rw["text"] for rw in row_words).strip()
        if full_text:
            s = _score_candidate(full_text, zone_width, row_bboxes[0] if row_bboxes else None)
            candidates.append(NameCandidate(full_text, s))

        # Also try individual 2–4 word subsequences
        texts = [rw["text"] for rw in row_words]
        for start in range(len(texts)):
            for end in range(start + 2, min(start + 5, len(texts) + 1)):
                sub = " ".join(texts[start:end]).strip()
                if sub and sub != full_text:
                    s = _score_candidate(sub, zone_width)
                    candidates.append(NameCandidate(sub, s))

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c.score)
    logger.debug("[name_ranker] Best: %r score=%.1f", best.text, best.score)

    if best.score < min_score:
        logger.info("[name_ranker] No candidate above min_score=%.1f (best=%.1f %r)",
                    min_score, best.score, best.text)
        return None

    # Title-case normalize
    cleaned = " ".join(w.capitalize() for w in best.text.split())
    logger.info("[name_ranker] Winner: %r (score=%.1f)", cleaned, best.score)
    return cleaned


def extract_best_name(ocr_text: str, zone_width: int = 0) -> Optional[str]:
    """
    Convenience wrapper: takes raw OCR block text, tokenizes into synthetic
    word records, and runs the ranker.

    Fast-path: if a 'CANDIDATE\'S FULL NAME' label is detected in the text,
    the line immediately following it is returned directly (after basic validation)
    without running the full scorer — this avoids ambiguity with noisy header lines.
    """
    if not ocr_text or not ocr_text.strip():
        return None

    # ── Label-anchor fast path ─────────────────────────────────────────────
    # Find the line after CANDIDATE / FULL NAME label
    lines = [ln.strip() for ln in ocr_text.splitlines()]
    for i, line in enumerate(lines):
        line_up = line.upper()
        if "CANDIDATE" in line_up or "FULL NAME" in line_up:
            # Return the next non-empty, non-label line
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = lines[j].strip()
                if not nxt:
                    continue
                # Must be at least 2 words, mostly alpha
                words = nxt.split()
                if len(words) < 2:
                    continue
                alpha_frac = sum(1 for w in words if re.fullmatch(r'[A-Za-z\.\-]+', w)) / len(words)
                if alpha_frac >= 0.8 and not _HAS_DIGIT.search(nxt):
                    cleaned = " ".join(w.capitalize() for w in words)
                    logger.info("[name_ranker] Label-anchored name: %r", cleaned)
                    return cleaned
            break  # found label but no valid line after it — fall through to ranker

    # ── Full scorer path ──────────────────────────────────────────────────
    records = []
    for i, line in enumerate(ocr_text.splitlines()):
        for j, word in enumerate(line.split()):
            records.append({
                "text": word,
                "bbox": (j * 50, i * 20, len(word) * 8, 18),
                "conf": 70.0,
            })

    return rank_name_candidates(records, zone_width=zone_width)
