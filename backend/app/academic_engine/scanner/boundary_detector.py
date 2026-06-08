"""
academic_engine/scanner/boundary_detector.py
============================================
STEP 1 — Document Boundary Detection.

Detects the actual paper / document edges and removes:
  - table / desk / floor background
  - hands, fingers
  - surrounding environment clutter

Technique stack:
  • Canny edge detection
  • Morphological closing to join broken edges
  • Contour finding + convex hull
  • Quadrilateral / polygon approximation (4-corner document)
  • Fallback: largest-area bounding rect

Returns the cropped document region as a numpy array (BGR).
"""

from __future__ import annotations

import cv2
import numpy as np
from typing import Optional, Tuple
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

# Minimum fraction of image area a candidate contour must occupy
MIN_AREA_FRACTION   = 0.05
# Maximum fraction (full-frame contour = likely no crop needed)
MAX_AREA_FRACTION   = 0.98
# Polygon approximation epsilon as fraction of contour perimeter
APPROX_EPSILON      = 0.02
# Canny thresholds
CANNY_LOW           = 30
CANNY_HIGH          = 100
# Kernel size for morphological closing
MORPH_KERNEL_SIZE   = (5, 5)
# Margin (pixels) to add around the detected bounding box when falling back
BBOX_MARGIN         = 10


# ── Internal helpers ──────────────────────────────────────────────────────────

def _preprocess_for_edges(image: np.ndarray) -> np.ndarray:
    """
    Convert to grayscale, apply CLAHE for contrast normalisation,
    then blur to suppress sensor noise before edge detection.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    return blurred


def _find_document_quad(
    image: np.ndarray,
) -> Optional[np.ndarray]:
    """
    Return the four corner points of the document as a (4,2) float32 array,
    or None if no suitable quadrilateral is found.

    Strategy:
      1. Canny edges
      2. Dilate + morphological close to seal broken contours
      3. Sort contours by area (descending)
      4. For each large contour, approximate as polygon
      5. Accept the first 4-point polygon that covers MIN_AREA_FRACTION
    """
    h, w = image.shape[:2]
    total_area = h * w

    processed = _preprocess_for_edges(image)
    edges = cv2.Canny(processed, CANNY_LOW, CANNY_HIGH)

    # Close gaps between edge segments
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, MORPH_KERNEL_SIZE)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)
    edges = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for cnt in contours[:10]:
        area = cv2.contourArea(cnt)
        if area < total_area * MIN_AREA_FRACTION:
            break
        if area > total_area * MAX_AREA_FRACTION:
            continue  # essentially entire frame — skip

        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, APPROX_EPSILON * peri, True)

        if len(approx) == 4:
            logger.debug(
                "[boundary_detector] Found 4-corner quad — area=%.1f (%.1f%% of frame)",
                area, 100 * area / total_area,
            )
            return approx.reshape(4, 2).astype(np.float32)

    # Relax: accept 4–6 sided polygon and take convex hull → 4 corners
    for cnt in contours[:10]:
        area = cv2.contourArea(cnt)
        if area < total_area * MIN_AREA_FRACTION:
            break
        if area > total_area * MAX_AREA_FRACTION:
            continue
        hull = cv2.convexHull(cnt)
        peri = cv2.arcLength(hull, True)
        approx = cv2.approxPolyDP(hull, APPROX_EPSILON * peri, True)
        if 3 <= len(approx) <= 6:
            rect = cv2.minAreaRect(approx)
            box  = cv2.boxPoints(rect).astype(np.float32)
            logger.debug(
                "[boundary_detector] Relaxed quad from %d-poly — area=%.1f",
                len(approx), area,
            )
            return box

    return None


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """
    Order 4 corner points as [top-left, top-right, bottom-right, bottom-left].
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s    = pts.sum(axis=1)
    diff = np.diff(pts, axis=1)

    rect[0] = pts[np.argmin(s)]      # top-left  — smallest sum
    rect[2] = pts[np.argmax(s)]      # bottom-right — largest sum
    rect[1] = pts[np.argmin(diff)]   # top-right — smallest diff
    rect[3] = pts[np.argmax(diff)]   # bottom-left — largest diff
    return rect


def _crop_with_bounding_rect(image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fallback: detect the largest non-white / non-background region via
    adaptive thresholding and crop its bounding rectangle.
    Returns (cropped, mask).
    """
    gray      = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel    = np.ones((20, 20), np.uint8)
    thresh    = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return image, np.ones(image.shape[:2], dtype=np.uint8) * 255

    cnt = max(contours, key=cv2.contourArea)
    x, y, w, h = cv2.boundingRect(cnt)

    # Add margin, clamp to image bounds
    ih, iw = image.shape[:2]
    x1 = max(0, x - BBOX_MARGIN)
    y1 = max(0, y - BBOX_MARGIN)
    x2 = min(iw, x + w + BBOX_MARGIN)
    y2 = min(ih, y + h + BBOX_MARGIN)

    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    mask[y1:y2, x1:x2] = 255

    logger.debug(
        "[boundary_detector] Fallback bbox crop: (%d,%d)→(%d,%d)", x1, y1, x2, y2
    )
    return image[y1:y2, x1:x2], mask


# ── Public API ────────────────────────────────────────────────────────────────

class BoundaryDetectionResult:
    """
    Holds the result of a boundary detection pass.

    Attributes:
        cropped   : np.ndarray — BGR image cropped to document bounds
        quad      : np.ndarray | None — 4-corner float32 array (ordered)
        method    : str — 'quad_detect' | 'bbox_fallback' | 'full_image'
        confidence: float — 0.0–1.0 estimate of detection quality
    """
    __slots__ = ("cropped", "quad", "method", "confidence")

    def __init__(
        self,
        cropped:    np.ndarray,
        quad:       Optional[np.ndarray],
        method:     str,
        confidence: float,
    ):
        self.cropped    = cropped
        self.quad       = quad
        self.method     = method
        self.confidence = confidence

    def __repr__(self) -> str:
        h, w = self.cropped.shape[:2]
        return (
            f"BoundaryDetectionResult(size={w}×{h}, "
            f"method={self.method!r}, confidence={self.confidence:.2f})"
        )


def detect_document_boundary(image: np.ndarray) -> BoundaryDetectionResult:
    """
    Detect and crop the document from *image* (BGR numpy array).

    Steps:
      1. Attempt quad detection via edge / contour analysis.
      2. If found → crop to quad bounding box (perspective correction
         is handled separately in perspective_corrector.py).
      3. If not found → fallback to largest-region bounding rect.
      4. If still nothing useful → return original image unchanged.

    Args:
        image: BGR numpy array (as returned by cv2.imread or equivalent)

    Returns:
        BoundaryDetectionResult
    """
    if image is None or image.size == 0:
        logger.warning("[boundary_detector] Received empty image")
        dummy = np.zeros((100, 100, 3), dtype=np.uint8)
        return BoundaryDetectionResult(dummy, None, "empty_input", 0.0)

    h, w = image.shape[:2]
    logger.info("[boundary_detector] Input image: %dx%d", w, h)

    quad = _find_document_quad(image)

    if quad is not None:
        ordered = _order_corners(quad)
        # Crop the axis-aligned bounding box of the quad
        xs = ordered[:, 0]
        ys = ordered[:, 1]
        x1, y1 = int(max(0, xs.min())), int(max(0, ys.min()))
        x2, y2 = int(min(w, xs.max())), int(min(h, ys.max()))
        cropped = image[y1:y2, x1:x2]

        crop_area = (x2 - x1) * (y2 - y1)
        total_area = h * w
        conf = 1.0 - abs(0.75 - crop_area / total_area)  # peak at 75% fill
        conf = float(np.clip(conf, 0.0, 1.0))

        logger.info(
            "[boundary_detector] quad_detect → crop (%d,%d)→(%d,%d) conf=%.2f",
            x1, y1, x2, y2, conf,
        )
        return BoundaryDetectionResult(cropped, ordered, "quad_detect", conf)

    # Fallback: bbox crop
    cropped, mask = _crop_with_bounding_rect(image)
    crop_area  = cropped.shape[0] * cropped.shape[1]
    total_area = h * w

    if crop_area < total_area * MIN_AREA_FRACTION:
        logger.warning(
            "[boundary_detector] No meaningful boundary found — returning full image"
        )
        return BoundaryDetectionResult(image.copy(), None, "full_image", 0.3)

    conf = 0.55  # moderate confidence for bbox fallback
    logger.info(
        "[boundary_detector] bbox_fallback → crop %dx%d conf=%.2f",
        cropped.shape[1], cropped.shape[0], conf,
    )
    return BoundaryDetectionResult(cropped, None, "bbox_fallback", conf)
