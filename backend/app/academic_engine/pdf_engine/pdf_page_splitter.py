"""
pdf_engine/pdf_page_splitter.py
================================
STEP 4 — Ordered page management for multi-page academic PDFs.

Supports:
  - Single-page marksheets (SSC/HSC)
  - Multi-page B.Tech/M.Tech transcripts (semester-wise)
  - University grade cards
  - Split certificate + marksheet combos

Returns clean, ordered page list with metadata hints.
"""
from __future__ import annotations

import logging
from typing import List, Dict, Any

import cv2
import numpy as np

logger = logging.getLogger("docvalidator")

# Minimum content area (fraction of page) to not be considered blank
_BLANK_THRESHOLD = 0.005

# Max pages to process (guard against huge PDFs)
_MAX_PAGES = 20


def _is_blank_page(img: np.ndarray) -> bool:
    """True if the page has negligible content (blank or near-blank)."""
    if img is None or img.size == 0:
        return True
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    # Content = pixels darker than 240
    content_pixels = np.sum(gray < 240)
    total_pixels   = gray.size
    ratio = content_pixels / max(total_pixels, 1)
    return ratio < _BLANK_THRESHOLD


def _classify_page_role(page_num: int, total_pages: int, text_hint: str = "") -> str:
    """
    Assign a semantic role to each page.

    Heuristics for common academic PDF layouts:
      - Page 1  → usually cover/header (name, URN, branch)
      - Middle  → semester tables
      - Last    → summary (CGPA, aggregate %, result)

    Returns: "header" | "semester" | "summary" | "general"
    """
    text_lower = text_hint.lower()

    # Summary page signals
    if any(kw in text_lower for kw in ["cgpa", "aggregate", "result", "total", "grand total", "cumulative"]):
        return "summary"

    # Semester table signals
    if any(kw in text_lower for kw in ["semester", "sem ", "spi", "sgpa", "subject code"]):
        return "semester"

    # First page — usually has identity fields
    if page_num == 1:
        return "header"

    # Last page — often summary
    if page_num == total_pages and total_pages > 1:
        return "summary"

    return "general"


def split_pages(rendered_pages: List[dict]) -> List[Dict[str, Any]]:
    """
    STEP 4 — Process and order rendered pages.

    Filters blank pages, caps at MAX_PAGES, assigns semantic roles.

    Args:
        rendered_pages: output from pdf_renderer.render_pdf_pages()

    Returns:
        List of page dicts (ordered):
            {
                page_number: int,
                image:       np.ndarray,
                role:        str,    # header | semester | summary | general
                is_blank:    bool,
                width:       int,
                height:      int,
            }
    """
    if not rendered_pages:
        return []

    # Cap total pages
    pages = rendered_pages[:_MAX_PAGES]
    if len(rendered_pages) > _MAX_PAGES:
        logger.warning(
            "[pdf_page_splitter] PDF has %d pages — processing first %d only",
            len(rendered_pages), _MAX_PAGES
        )

    total = len(pages)
    result = []

    for page in pages:
        img      = page.get("image")
        page_num = page.get("page_number", 0)
        native   = page.get("native_text", "")

        blank = _is_blank_page(img)
        role  = _classify_page_role(page_num, total, native) if not blank else "blank"

        if blank:
            logger.debug("[pdf_page_splitter] Page %d is blank — skipping", page_num)

        h, w = img.shape[:2] if img is not None else (0, 0)

        result.append({
            "page_number": page_num,
            "image":       img,
            "role":        role,
            "is_blank":    blank,
            "width":       w,
            "height":      h,
            "native_text": native,
        })

    non_blank = [p for p in result if not p["is_blank"]]
    logger.info(
        "[pdf_page_splitter] %d total pages, %d non-blank, roles: %s",
        total,
        len(non_blank),
        [p["role"] for p in non_blank],
    )

    return result
