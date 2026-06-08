"""
academic_engine/layout_v2/anchor_mapper.py
==========================================
Spatial anchor-to-value mapping.

RULE: NEVER extract from merged OCR text blindly.
Instead:
  1. Detect label word (e.g. "Percentage:")
  2. Find nearest value word/block using geometric proximity
  3. Validate the relationship makes spatial sense
  4. Return field → value mapping

This is the "spatial parser" — it understands document layout as
a 2D structure, not a linear text stream.

Supports:
  - Right-of-label values (most common: "Percentage : 75.17")
  - Below-label values  (stacked layout: "Percentage\n75.17")
  - Table-cell values   (cell to the right in a table row)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.logger import logger
from app.academic_engine.layout_v2.spatial_relationships import (
    BBox, bbox_center, same_row, is_right_of, is_above,
    vertical_distance, horizontal_overlap, group_into_rows,
)


# ── Field definitions ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldSpec:
    name:           str
    label_patterns: List[str]    # regex patterns matching label text
    value_pattern:  str          # regex for valid value text
    search_right:   bool = True  # look for value to the right
    search_below:   bool = True  # look for value below
    max_h_gap_px:   int  = 250   # max horizontal pixel gap label→value
    max_v_gap_px:   int  = 60    # max vertical pixel gap label→value


FIELD_SPECS = [
    FieldSpec(
        name           = "percentage",
        label_patterns = [
            r"percent(?:age)?", r"total\s*%", r"marks\s*%",
            r"टक्के", r"aggregate", r"overall",
        ],
        value_pattern  = r"\d{1,3}(?:\.\d{1,2})?%?",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 300,
        max_v_gap_px   = 80,
    ),
    FieldSpec(
        name           = "cgpa",
        label_patterns = [r"cgpa", r"sgpa", r"gpa", r"grade\s*point"],
        value_pattern  = r"\d{1,2}(?:\.\d{1,2})?",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 250,
        max_v_gap_px   = 80,
    ),
    FieldSpec(
        name           = "result",
        label_patterns = [
            r"result", r"decision", r"परिणाम", r"निर्णय",
        ],
        value_pattern  = r"[A-Za-z\s]{3,}",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 300,
        max_v_gap_px   = 80,
    ),
    FieldSpec(
        name           = "grade_class",
        label_patterns = [
            r"class", r"division", r"grade", r"श्रेणी",
        ],
        value_pattern  = r"[A-Za-z\s\+]{3,}",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 300,
        max_v_gap_px   = 80,
    ),
    FieldSpec(
        name           = "candidate_name",
        label_patterns = [
            r"name\s*of\s*(?:the\s*)?(?:student|candidate|examinee)",
            r"candidate(?:'s)?\s*name", r"student\s*name",
            r"विद्यार्थ्याचे\s*नाव",
        ],
        value_pattern  = r"[A-Za-z\s\.]{4,}",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 400,
        max_v_gap_px   = 60,
    ),
    FieldSpec(
        name           = "board_university",
        label_patterns = [
            r"board", r"university", r"institute", r"college",
        ],
        value_pattern  = r"[A-Za-z\s\.]{5,}",
        search_right   = False,  # Usually the board name IS the label line
        search_below   = False,
        max_h_gap_px   = 0,
        max_v_gap_px   = 0,
    ),
    FieldSpec(
        name           = "passing_year",
        label_patterns = [
            r"year\s*of\s*pass(?:ing)?", r"exam\s*year",
            r"year", r"session", r"वर्ष",
        ],
        value_pattern  = r"20\d{2}",
        search_right   = True,
        search_below   = True,
        max_h_gap_px   = 250,
        max_v_gap_px   = 60,
    ),
]


# ── Word record type ──────────────────────────────────────────────────────────

WordRecord = Dict  # {text: str, bbox: BBox, conf: float}


# ── Matcher ───────────────────────────────────────────────────────────────────

class AnchorMapper:
    """
    Maps field labels to their nearest valid values using spatial proximity.
    """

    def map_fields(self, words: List[WordRecord]) -> Dict[str, Optional[str]]:
        """
        Given a list of word records (text + bbox), extract field values
        by finding label → value spatial relationships.

        Args:
            words: List of {text, bbox, conf} dicts from Tesseract data output.

        Returns:
            Dict of field_name → extracted_value (or None).
        """
        result: Dict[str, Optional[str]] = {f.name: None for f in FIELD_SPECS}

        if not words:
            return result

        for spec in FIELD_SPECS:
            value = self._extract_field(spec, words)
            if value:
                result[spec.name] = value
                logger.debug("[anchor_mapper] %s → %r", spec.name, value)

        return result

    def _extract_field(self, spec: FieldSpec, words: List[WordRecord]) -> Optional[str]:
        """Find label word(s) then locate nearest value matching spec.value_pattern."""
        label_pattern = re.compile(
            "|".join(f"(?:{p})" for p in spec.label_patterns),
            re.IGNORECASE,
        )
        value_re = re.compile(spec.value_pattern, re.IGNORECASE)

        # Find all label words
        label_words = [
            w for w in words
            if label_pattern.search(w["text"])
        ]
        if not label_words:
            return None

        # Use the highest-confidence label
        label_word = max(label_words, key=lambda w: w.get("conf", 0))
        lbbox      = label_word["bbox"]

        # Special case: board_university — the label line IS the value
        if not spec.search_right and not spec.search_below:
            return label_word["text"].strip()

        # Search for value word
        best_value = None
        best_dist  = float("inf")

        for w in words:
            if w is label_word:
                continue
            vtext = w["text"].strip()
            if not value_re.search(vtext):
                continue

            vbbox = w["bbox"]
            lx, ly, lw, lh = lbbox
            vx, vy, vw, vh = vbbox
            lcx, lcy = lx + lw / 2, ly + lh / 2
            vcx, vcy = vx + vw / 2, vy + vh / 2

            h_gap = vcx - (lx + lw)
            v_gap = vcy - lcy

            # Filter by allowed search directions
            right_ok = spec.search_right and 0 <= h_gap <= spec.max_h_gap_px
            below_ok = spec.search_below and 0 <= v_gap <= spec.max_v_gap_px

            if not (right_ok or below_ok):
                continue

            # Reject values that are clearly in the noise/subject table area
            # (too many digits = table row, not summary value)
            if len(re.findall(r"\d", vtext)) > 5:
                continue

            dist = ((vcx - lcx) ** 2 + (vcy - lcy) ** 2) ** 0.5
            if dist < best_dist:
                best_dist  = dist
                best_value = vtext

        return best_value


# ── Module-level convenience ──────────────────────────────────────────────────

_mapper = AnchorMapper()


def map_anchor_fields(words: List[WordRecord]) -> Dict[str, Optional[str]]:
    """Module-level wrapper: map spatial anchors to field values."""
    return _mapper.map_fields(words)
