"""
academic_engine/scanner/perspective_corrector.py
================================================
STEP 2 + STEP 3 — Perspective Correction & Auto Rotation.

Fixes:
  • Tilted camera angles
  • Trapezoid / keystone distortion
  • Skewed photos (document not parallel to camera plane)
  • Upside-down, sideways, and arbitrarily rotated scans

Technique:
  • Four-corner homography warp (like Adobe Scan / DigiLocker)
  • Deskew via Hough line / projection-profile method
  • Auto-rotation via text orientation detection

Output: flat rectangular document image.
"""

from __future__ import annotations

import math
import cv2
import numpy as np
from typing import Optional, Tuple
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

TARGET_LONG_EDGE  = 2480   # A4 at 300 DPI long edge (pixels)
TARGET_SHORT_EDGE = 1754   # A4 at 300 DPI short edge (pixels)
DESKEW_ANGLE_LIMIT = 45.0  # Only correct if skew < this (degrees)
ROTATION_CANDIDATES = [0, 90, 180, 270]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_output_size(
    tl: np.ndarray,
    tr: np.ndarray,
    br: np.ndarray,
    bl: np.ndarray,
) -> Tuple[int, int]:
    """Estimate the natural output width and height from 4 corners."""
    width_top    = np.linalg.norm(tr - tl)
    width_bottom = np.linalg.norm(br - bl)
    width  = int(max(width_top, width_bottom))

    height_left  = np.linalg.norm(bl - tl)
    height_right = np.linalg.norm(br - tr)
    height = int(max(height_left, height_right))

    return width, height


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Apply a perspective warp using 4 ordered corner points.
    pts must be [top-left, top-right, bottom-right, bottom-left] float32.
    """
    tl, tr, br, bl = pts

    w, h = _compute_output_size(tl, tr, br, bl)
    if w <= 0 or h <= 0:
        logger.warning("[perspective_corrector] Invalid output size %dx%d", w, h)
        return image

    dst = np.array(
        [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]],
        dtype=np.float32,
    )

    M       = cv2.getPerspectiveTransform(pts.astype(np.float32), dst)
    warped  = cv2.warpPerspective(
        image, M, (w, h),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    logger.info(
        "[perspective_corrector] Warped to %dx%d via homography", w, h
    )
    return warped


# ── Deskew via projection profile ─────────────────────────────────────────────

def _projection_profile_skew(gray: np.ndarray, angle_range: float = 5.0) -> float:
    """
    Estimate skew angle using horizontal projection profile variance.
    Sweeps ±angle_range degrees and picks the angle with maximum row variance
    (text rows are most separated when document is straight).
    Returns angle in degrees to rotate by (positive = counter-clockwise).
    """
    best_angle = 0.0
    best_score = -1.0

    for angle in np.arange(-angle_range, angle_range + 0.5, 0.5):
        M       = cv2.getRotationMatrix2D(
            (gray.shape[1] / 2, gray.shape[0] / 2), angle, 1.0
        )
        rotated = cv2.warpAffine(
            gray, M, (gray.shape[1], gray.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderValue=255,
        )
        # Binarise
        _, bw = cv2.threshold(rotated, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        # Horizontal projection profile
        profile = np.sum(bw, axis=1).astype(np.float64)
        score   = float(profile.var())
        if score > best_score:
            best_score = score
            best_angle = angle

    logger.debug(
        "[perspective_corrector] Projection-profile deskew: %.2f°", best_angle
    )
    return best_angle


def _hough_skew(gray: np.ndarray) -> float:
    """
    Estimate skew from dominant horizontal lines via probabilistic Hough.
    Returns angle in degrees (positive = counter-clockwise correction).
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=80,
        minLineLength=gray.shape[1] // 4,
        maxLineGap=20,
    )
    if lines is None:
        return 0.0

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 == x1:
            continue
        angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
        # Keep only near-horizontal lines (±45°)
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return 0.0
    median_angle = float(np.median(angles))
    logger.debug("[perspective_corrector] Hough skew: %.2f°", median_angle)
    return median_angle


def _rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotate image by *angle* degrees (counter-clockwise), expanding canvas."""
    h, w   = image.shape[:2]
    cx, cy = w / 2, h / 2
    M      = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)

    # Expand canvas to avoid clipping
    cos = abs(M[0, 0])
    sin = abs(M[0, 1])
    nw  = int(h * sin + w * cos)
    nh  = int(h * cos + w * sin)
    M[0, 2] += nw / 2 - cx
    M[1, 2] += nh / 2 - cy

    rotated = cv2.warpAffine(
        image, M, (nw, nh),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(255, 255, 255),
    )
    return rotated


# ── Auto rotation (0/90/180/270) ──────────────────────────────────────────────

def _score_orientation(gray: np.ndarray) -> float:
    """
    Heuristic: score an orientation by how many strong horizontal text lines
    are detected (more horizontal lines = more likely upright text).
    """
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=50,
        minLineLength=gray.shape[1] // 6,
        maxLineGap=10,
    )
    if lines is None:
        return 0.0
    angles = [math.degrees(math.atan2(l[0][3] - l[0][1], l[0][2] - l[0][0]))
               for l in lines]
    horizontal = sum(1 for a in angles if abs(a) < 15)
    return float(horizontal)


def auto_rotate(image: np.ndarray) -> Tuple[np.ndarray, int]:
    """
    Try all four 90° rotations and pick the one with the most horizontal lines.
    Returns (corrected_image, rotation_angle_applied).
    """
    gray    = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scores  = {}
    for angle in ROTATION_CANDIDATES:
        if angle == 0:
            candidate = gray
        else:
            M  = cv2.getRotationMatrix2D((gray.shape[1]//2, gray.shape[0]//2), angle, 1.0)
            candidate = cv2.warpAffine(gray, M, (gray.shape[1], gray.shape[0]))
        scores[angle] = _score_orientation(candidate)

    best_angle = max(scores, key=scores.__getitem__)
    logger.info(
        "[perspective_corrector] Auto-rotate scores: %s → best=%d°",
        {k: round(v) for k, v in scores.items()}, best_angle,
    )

    if best_angle == 0:
        return image, 0

    rotated = _rotate_image(image, float(best_angle))
    return rotated, best_angle


# ── Public API ────────────────────────────────────────────────────────────────

class PerspectiveCorrectionResult:
    """
    Result of perspective correction.

    Attributes:
        image         : np.ndarray — corrected BGR image
        method        : str — 'homography' | 'deskew' | 'passthrough'
        skew_angle    : float — detected skew (degrees)
        rotation_applied: int — 0/90/180/270 coarse rotation applied
        confidence    : float — 0.0–1.0
    """
    __slots__ = ("image", "method", "skew_angle", "rotation_applied", "confidence")

    def __init__(
        self,
        image:             np.ndarray,
        method:            str,
        skew_angle:        float = 0.0,
        rotation_applied:  int   = 0,
        confidence:        float = 1.0,
    ):
        self.image            = image
        self.method           = method
        self.skew_angle       = skew_angle
        self.rotation_applied = rotation_applied
        self.confidence       = confidence

    def __repr__(self) -> str:
        h, w = self.image.shape[:2]
        return (
            f"PerspectiveCorrectionResult(size={w}×{h}, method={self.method!r}, "
            f"skew={self.skew_angle:.1f}°, rot={self.rotation_applied}°, "
            f"conf={self.confidence:.2f})"
        )


def correct_perspective(
    image: np.ndarray,
    quad:  Optional[np.ndarray] = None,
) -> PerspectiveCorrectionResult:
    """
    Apply perspective correction to *image*.

    Args:
        image : BGR numpy array
        quad  : Optional 4-corner array [TL, TR, BR, BL] float32 from
                boundary_detector.  If provided, uses full homography warp.
                If None, falls back to deskew-only.

    Returns:
        PerspectiveCorrectionResult
    """
    if image is None or image.size == 0:
        logger.warning("[perspective_corrector] Empty image received")
        dummy = np.zeros((100, 100, 3), dtype=np.uint8)
        return PerspectiveCorrectionResult(dummy, "empty_input", confidence=0.0)

    h, w = image.shape[:2]
    logger.info("[perspective_corrector] Input: %dx%d", w, h)

    # ── Step A: coarse auto-rotation ──────────────────────────────────────────
    image, rot_applied = auto_rotate(image)

    # ── Step B: homography warp if quad available ─────────────────────────────
    if quad is not None and len(quad) == 4:
        try:
            warped = _four_point_transform(image, quad)
            gray   = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
            skew   = _projection_profile_skew(gray, angle_range=3.0)
            if abs(skew) > 0.3:
                warped = _rotate_image(warped, skew)
            return PerspectiveCorrectionResult(
                warped, "homography",
                skew_angle=skew,
                rotation_applied=rot_applied,
                confidence=0.92,
            )
        except Exception as exc:
            logger.warning("[perspective_corrector] Homography failed: %s", exc)

    # ── Step C: deskew only ───────────────────────────────────────────────────
    gray  = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Try Hough first, fall back to projection profile
    skew = _hough_skew(gray)
    if abs(skew) < 0.3 or abs(skew) > DESKEW_ANGLE_LIMIT:
        skew = _projection_profile_skew(gray, angle_range=5.0)

    if abs(skew) > 0.3 and abs(skew) <= DESKEW_ANGLE_LIMIT:
        corrected = _rotate_image(image, skew)
        logger.info("[perspective_corrector] Deskew applied: %.2f°", skew)
        return PerspectiveCorrectionResult(
            corrected, "deskew",
            skew_angle=skew,
            rotation_applied=rot_applied,
            confidence=0.75,
        )

    logger.info("[perspective_corrector] Passthrough (skew=%.2f° — below threshold)", skew)
    return PerspectiveCorrectionResult(
        image, "passthrough",
        skew_angle=skew,
        rotation_applied=rot_applied,
        confidence=0.65,
    )
