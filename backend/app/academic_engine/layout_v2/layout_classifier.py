"""
academic_engine/layout_v2/layout_classifier.py
===============================================
Classify the LAYOUT VARIANT of a restored document image.

Output determines which zone strategy + extraction rules to apply:

  Layout classes:
    SSC_MARKSHEET      — Maharashtra / CBSE 10th board marksheet
    HSC_MARKSHEET      — Maharashtra / CBSE 12th board marksheet
    DEGREE_MARKSHEET   — University semester / consolidated marksheet
    CERTIFICATE        — Passing / participation / merit certificate
    DIPLOMA_MARKSHEET  — Diploma / ITI marksheet
    UNKNOWN            — Could not classify reliably

Each class carries:
  - orientation:  'portrait' | 'landscape'
  - header_height: fraction  — estimated header zone height
  - has_subject_table: bool  — whether a subject table is expected
  - summary_position: 'bottom' | 'right' | 'middle'
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import numpy as np
import cv2

from app.core.logger import logger


# ── OCR noise normalization (same as document_classifier) ────────────────────

def _normalize_for_scoring(text: str) -> str:
    """Repair common OCR confusions before keyword scoring."""
    import re
    repairs = [
        (r"\bH[1I]GHER\b",           "HIGHER"),
        (r"\bSEC[O0]NDARY\b",        "SECONDARY"),
        (r"\bCERT[1I]F[1I]CATE\b",  "CERTIFICATE"),
        (r"\bSECONDARY\b",           "SECONDARY"),
        (r"\bB[O0]ARD\b",            "BOARD"),
        (r"\bSCH[O0][O0]L\b",        "SCHOOL"),
        (r"\bUNIVERS[1I]TY\b",       "UNIVERSITY"),
        (r"\bSTATEMENT\b",           "STATEMENT"),
        (r"\bMARKS?\b",              "MARKS"),
        (r"\bR[E3]SULT\b",           "RESULT"),
        (r"\bPERCENTAGE\b",          "PERCENTAGE"),
    ]
    for pattern, replacement in repairs:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# ── Layout variant definitions ────────────────────────────────────────────────

@dataclass(frozen=True)
class LayoutVariant:
    layout_class:      str
    orientation:       str          # 'portrait' | 'landscape'
    header_frac:       float        # fraction of H for header zone bottom
    candidate_frac:    Tuple[float, float]   # (start, end) fractions of H
    subject_frac:      Tuple[float, float]   # (start, end)  — None if no table
    summary_frac:      Tuple[float, float]   # (start, end)
    noise_frac_start:  float        # fraction where noise/QR zone starts
    has_subject_table: bool
    summary_position:  str          # 'bottom' | 'right' | 'center'
    score_keywords:    List[str]    # keywords that identify this layout


_VARIANTS: List[LayoutVariant] = [
    LayoutVariant(
        layout_class     = "SSC_MARKSHEET",
        orientation      = "portrait",
        header_frac      = 0.18,
        candidate_frac   = (0.14, 0.36),
        subject_frac     = (0.30, 0.72),
        summary_frac     = (0.62, 0.86),
        noise_frac_start = 0.84,
        has_subject_table= True,
        summary_position = "bottom",
        score_keywords   = [
            "secondary school certificate", "ssc", "10th", "class x",
            "board of secondary", "maharashtra state board",
            "central board of secondary", "cbse",
        ],
    ),
    LayoutVariant(
        layout_class     = "HSC_MARKSHEET",
        orientation      = "portrait",
        header_frac      = 0.16,
        candidate_frac   = (0.12, 0.34),
        subject_frac     = (0.28, 0.70),
        summary_frac     = (0.60, 0.84),
        noise_frac_start = 0.82,
        has_subject_table= True,
        summary_position = "bottom",
        score_keywords   = [
            "higher secondary", "hsc", "12th", "class xii",
            "higher secondary certificate", "std. xii",
            "higher secondary school", "h.s.c",
        ],
    ),
    LayoutVariant(
        layout_class     = "DEGREE_MARKSHEET",
        orientation      = "portrait",
        header_frac      = 0.20,
        candidate_frac   = (0.16, 0.38),
        subject_frac     = (0.32, 0.74),
        summary_frac     = (0.65, 0.88),
        noise_frac_start = 0.86,
        has_subject_table= True,
        summary_position = "bottom",
        score_keywords   = [
            "university", "b.e", "b.tech", "b.sc", "b.com", "b.a",
            "bachelor", "engineering", "semester", "cgpa", "sgpa",
            "annual result", "provisional", "consolidated",
        ],
    ),
    LayoutVariant(
        layout_class     = "CERTIFICATE",
        orientation      = "landscape",
        header_frac      = 0.28,
        candidate_frac   = (0.22, 0.60),
        subject_frac     = (0.00, 0.00),  # no table
        summary_frac     = (0.50, 0.85),
        noise_frac_start = 0.90,
        has_subject_table= False,
        summary_position = "center",
        score_keywords   = [
            "certificate", "this is to certify", "hereby certify",
            "awarded", "distinction", "merit", "participation",
        ],
    ),
    LayoutVariant(
        layout_class     = "DIPLOMA_MARKSHEET",
        orientation      = "portrait",
        header_frac      = 0.18,
        candidate_frac   = (0.14, 0.36),
        subject_frac     = (0.30, 0.72),
        summary_frac     = (0.62, 0.86),
        noise_frac_start = 0.84,
        has_subject_table= True,
        summary_position = "bottom",
        score_keywords   = [
            "diploma", "polytechnic", "iti", "vocational",
            "msbte", "technical education",
        ],
    ),
]


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_variant(text: str, variant: LayoutVariant) -> int:
    # Normalize before scoring so OCR noise doesn't kill keyword matches
    t = _normalize_for_scoring(text).lower()
    score = 0
    for kw in variant.score_keywords:
        if kw in t:
            score += 1
    return score


def classify_layout(
    text: str,
    img:  Optional[np.ndarray] = None,
) -> LayoutVariant:
    """
    Classify the layout variant of a document.

    Args:
        text: Full-page or partial OCR text from the document.
        img:  Optional image array — used for aspect-ratio check.

    Returns:
        The best-matching LayoutVariant.
    """
    # Aspect-ratio check
    is_landscape = False
    if img is not None:
        h, w = img.shape[:2]
        is_landscape = w > h * 1.25

    # Score each variant
    scored = [(v, _score_variant(text, v)) for v in _VARIANTS]

    # Filter by orientation if image is available
    if img is not None:
        orient = "landscape" if is_landscape else "portrait"
        # If landscape, strongly boost CERTIFICATE
        if is_landscape:
            scored = [
                (v, s + (5 if v.orientation == "landscape" else 0))
                for v, s in scored
            ]

    best_variant, best_score = max(scored, key=lambda x: x[1])

    if best_score == 0:
        # Default: HSC_MARKSHEET (most common)
        best_variant = _VARIANTS[1]  # HSC
        logger.info("[layout_classifier] No keyword match — defaulting to HSC_MARKSHEET")
    else:
        logger.info(
            "[layout_classifier] Classified as %s (score=%d)",
            best_variant.layout_class, best_score,
        )

    return best_variant


def get_variant_by_class(layout_class: str) -> Optional[LayoutVariant]:
    for v in _VARIANTS:
        if v.layout_class == layout_class:
            return v
    return None
