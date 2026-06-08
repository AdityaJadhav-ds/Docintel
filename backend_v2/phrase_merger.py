"""
phrase_merger.py — Horizontal Phrase Merger

Merges adjacent words on the same line into phrase tokens.
This is a MANDATORY step before any column snapping.

Without this:
  - Each tiny OCR word gets its own column anchor
  - "Branch Code" becomes two fake columns
  - "Factory Sangli 416416" explodes into 4+ columns

With this:
  - Words close together become a single phrase token
  - Column anchors are computed from phrases, not raw words
  - Grid is stable and human-readable

PIPELINE POSITION:
  line_engine → [phrase_merger] → region_engine → table_engine
"""
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import List
from layout_tree import Word, Line

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Phrase token — a merged group of adjacent words within a line
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Phrase:
    """A merged group of words on the same line."""
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    cx: float       # center x of merged phrase
    cy: float       # center y of merged phrase
    width: float
    height: float
    words: List[Word] = field(default_factory=list)   # source words


# ─────────────────────────────────────────────────────────────────────────────
# Main merge logic
# ─────────────────────────────────────────────────────────────────────────────

def merge_phrases(lines: List[Line]) -> List[Line]:
    """
    For every Line, merge horizontally adjacent words into Phrases.
    The Phrases replace Line.words in-place (as Word-compatible objects).

    Gap threshold: adaptive per line.
      = max(8px, 1.5 × median_char_width_of_line)

    Returns the same list of Line objects with words replaced by merged phrases
    (Phrase is duck-typed as Word — same attributes).
    """
    if not lines:
        return lines

    # Estimate global median char width from all words for a sane default
    all_widths = []
    for line in lines:
        for w in line.words:
            if w.text and w.width > 0:
                char_w = w.width / max(len(w.text), 1)
                all_widths.append(char_w)

    global_median_char_w = float(np.median(all_widths)) if all_widths else 8.0

    merged_lines = []
    for line in lines:
        new_words = _merge_line_words(line.words, global_median_char_w)
        # Rebuild Line with merged phrases as its words
        if new_words:
            new_line = Line(
                line_id=line.line_id,
                words=new_words,
                text=" ".join(w.text for w in new_words),
                x1=min(w.x1 for w in new_words),
                y1=min(w.y1 for w in new_words),
                x2=max(w.x2 for w in new_words),
                y2=max(w.y2 for w in new_words),
                cy=line.cy,
            )
        else:
            new_line = line
        merged_lines.append(new_line)

    total_before = sum(len(l.words) for l in lines)
    total_after  = sum(len(l.words) for l in merged_lines)
    logger.debug(
        "phrase_merger: %d words → %d phrases across %d lines",
        total_before, total_after, len(lines)
    )
    return merged_lines


def _merge_line_words(words: List[Word], global_median_char_w: float) -> List[Word]:
    """
    Merge adjacent words within a single line into Phrase objects.
    Words are expected to be sorted left→right.
    """
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: w.x1)

    # Per-line adaptive gap threshold
    widths = [w.width / max(len(w.text), 1) for w in sorted_words if w.text and w.width > 0]
    median_char_w = float(np.median(widths)) if widths else global_median_char_w
    gap_thresh = max(8.0, median_char_w * 1.8)

    phrases: List[Word] = []
    group = [sorted_words[0]]

    for w in sorted_words[1:]:
        prev = group[-1]
        gap = w.x1 - prev.x2

        if gap <= gap_thresh:
            # Close enough — merge into current group
            group.append(w)
        else:
            # Gap too large — flush current group as phrase
            phrases.append(_group_to_phrase(group))
            group = [w]

    if group:
        phrases.append(_group_to_phrase(group))

    return phrases


def _group_to_phrase(group: List[Word]) -> Word:
    """Combine a list of words into a single Word (phrase token)."""
    text = " ".join(w.text for w in group)
    x1 = min(w.x1 for w in group)
    y1 = min(w.y1 for w in group)
    x2 = max(w.x2 for w in group)
    y2 = max(w.y2 for w in group)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    return Word(
        text=text,
        x1=x1, y1=y1, x2=x2, y2=y2,
        cx=cx, cy=cy,
        width=x2 - x1,
        height=y2 - y1,
    )
