"""
academic_engine/layout_v2/table_detector.py
============================================
Detect and mask subject-table regions in academic documents.

Subject tables contain:
  - rows of subject names and marks
  - table borders and grid lines
  - bilingual labels (Marathi / Hindi headers)
  - repeated numbers that confuse field extraction

Strategy:
  1. Detect horizontal line density (table rows = many parallel H lines)
  2. Detect grid structure via Hough line transform
  3. Estimate table bounding box
  4. Return mask + bounding rect to exclude from extraction

Output:
  TableDetectionResult with:
    - found:       bool
    - bbox:        (x, y, w, h) — bounding box of table region
    - mask:        numpy binary mask (255 = table, 0 = clean)
    - confidence:  float 0–1
"""

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from app.core.logger import logger

BBox = Tuple[int, int, int, int]


# ── Constants ─────────────────────────────────────────────────────────────────

MIN_TABLE_AREA_FRACTION  = 0.05   # table must cover at least 5% of image area
MIN_HLINES_FOR_TABLE     = 4      # minimum horizontal lines to declare a table
HLINE_MIN_WIDTH_FRACTION = 0.35   # H-lines must span this fraction of image width
VLINE_MIN_HEIGHT_FRACTION= 0.04   # V-lines must span this fraction of image height
KERNEL_H = (1, 40)                # horizontal line kernel
KERNEL_V = (40, 1)                # vertical line kernel


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class TableDetectionResult:
    found:      bool              = False
    bbox:       Optional[BBox]    = None
    mask:       Optional[np.ndarray] = None
    confidence: float             = 0.0
    h_lines:    int               = 0
    v_lines:    int               = 0

    def __repr__(self) -> str:
        return (
            f"TableDetectionResult(found={self.found}, bbox={self.bbox}, "
            f"h_lines={self.h_lines}, v_lines={self.v_lines}, conf={self.confidence:.2f})"
        )


# ── Core detection ────────────────────────────────────────────────────────────

def _detect_lines(gray: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect horizontal and vertical line masks using morphological operations.
    Returns (h_mask, v_mask) as binary uint8 images.
    """
    h, w = gray.shape

    # Threshold
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Horizontal lines
    kh = cv2.getStructuringElement(cv2.MORPH_RECT, KERNEL_H)
    h_mask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kh, iterations=1)

    # Vertical lines
    kv = cv2.getStructuringElement(cv2.MORPH_RECT, KERNEL_V)
    v_mask = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kv, iterations=1)

    return h_mask, v_mask


def _count_significant_lines(
    mask: np.ndarray,
    axis: int,            # 0 = count rows (H-lines), 1 = count cols (V-lines)
    min_span: int,
) -> List[int]:
    """
    Project mask along axis.  Return y-positions (axis=0) or x-positions
    (axis=1) where a significant line is present.
    """
    projection = np.sum(mask, axis=axis)
    # A "significant" line has ≥ min_span non-zero pixels
    positions  = [i for i, v in enumerate(projection) if v >= min_span]
    return positions


def _lines_to_row_groups(positions: List[int], gap: int = 10) -> List[Tuple[int, int]]:
    """
    Cluster y-positions (each horizontal line may be a few pixels thick).
    Returns list of (min_y, max_y) groups.
    """
    if not positions:
        return []
    groups = []
    start  = positions[0]
    prev   = positions[0]
    for p in positions[1:]:
        if p - prev > gap:
            groups.append((start, prev))
            start = p
        prev = p
    groups.append((start, prev))
    return groups


def detect_table(image: np.ndarray) -> TableDetectionResult:
    """
    Detect subject table in document image.

    Args:
        image: BGR numpy array (the restored document image)

    Returns:
        TableDetectionResult
    """
    if image is None or image.size == 0:
        return TableDetectionResult()

    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Minimum line spans
    min_h_span = int(HLINE_MIN_WIDTH_FRACTION  * w)
    min_v_span = int(VLINE_MIN_HEIGHT_FRACTION * h)

    h_mask, v_mask = _detect_lines(gray)

    # Count horizontal rows
    h_positions = _count_significant_lines(h_mask, axis=1, min_span=min_h_span)
    h_groups    = _lines_to_row_groups(h_positions, gap=15)
    n_hlines    = len(h_groups)

    # Count vertical columns
    v_positions = _count_significant_lines(v_mask, axis=0, min_span=min_v_span)
    v_groups    = _lines_to_row_groups(v_positions, gap=15)
    n_vlines    = len(v_groups)

    logger.debug(
        "[table_detector] H-line groups=%d  V-line groups=%d", n_hlines, n_vlines
    )

    if n_hlines < MIN_HLINES_FOR_TABLE:
        logger.info("[table_detector] No significant table found (h_lines=%d)", n_hlines)
        return TableDetectionResult(h_lines=n_hlines, v_lines=n_vlines)

    # Estimate table bounding box from line positions
    all_y = [y for s, e in h_groups for y in (s, e)]
    all_x = [x for s, e in v_groups for x in (s, e)] if v_groups else [0, w]

    y_top    = max(0, min(all_y) - 10)
    y_bottom = min(h, max(all_y) + 10)
    x_left   = max(0, min(all_x) - 10)
    x_right  = min(w, max(all_x) + 10)

    # If x coverage is too narrow, use full width
    if x_right - x_left < w * 0.4:
        x_left  = 0
        x_right = w

    table_bbox = (x_left, y_top, x_right - x_left, y_bottom - y_top)
    table_area = table_bbox[2] * table_bbox[3]

    if table_area < h * w * MIN_TABLE_AREA_FRACTION:
        logger.info("[table_detector] Table region too small — ignoring")
        return TableDetectionResult(h_lines=n_hlines, v_lines=n_vlines)

    # Build mask
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[y_top:y_bottom, x_left:x_right] = 255

    # Confidence based on line count and coverage
    coverage   = table_area / (h * w)
    conf       = float(np.clip(n_hlines / 12.0, 0, 1) * 0.6 + min(coverage / 0.4, 1) * 0.4)

    logger.info(
        "[table_detector] Table found: bbox=%s h_lines=%d v_lines=%d conf=%.2f",
        table_bbox, n_hlines, n_vlines, conf,
    )
    return TableDetectionResult(
        found      = True,
        bbox       = table_bbox,
        mask       = mask,
        confidence = conf,
        h_lines    = n_hlines,
        v_lines    = n_vlines,
    )


def mask_table_region(image: np.ndarray, table_result: TableDetectionResult) -> np.ndarray:
    """
    Whitewash the table region in the image.
    Returns the image with table area blanked out (white-filled).
    """
    if not table_result.found or table_result.bbox is None:
        return image
    result = image.copy()
    x, y, w, h = table_result.bbox
    result[y:y+h, x:x+w] = 255
    return result


def detect_and_mask_table(image: np.ndarray) -> Tuple[np.ndarray, TableDetectionResult]:
    """
    Convenience: detect table + return both masked image and result.
    """
    result  = detect_table(image)
    masked  = mask_table_region(image, result)
    return masked, result
