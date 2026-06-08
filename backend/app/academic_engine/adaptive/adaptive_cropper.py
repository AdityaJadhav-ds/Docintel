"""
academic_engine/adaptive/adaptive_cropper.py
=============================================
Multi-strategy ROI crop generator.

For any field ROI that fails primary extraction, generates a ranked list
of alternative crops to try. Each strategy is labelled and scored.

Strategies (in order of escalation):
  1. exact      — the original anchor-derived bbox (pass-through)
  2. expand_h   — expand horizontally ±pct of image width
  3. expand_v   — expand vertically ±pct of image height
  4. shift_down — shift crop downward by half its height
  5. shift_right— shift crop rightward by ¼ of image width
  6. strip_full — the entire horizontal strip at the label's y-level
  7. contour    — largest connected-component region in the zone
  8. zone_full  — the entire summary zone (maximum fallback)

Output:
  list of CropVariant(strategy, image, bbox)
"""

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from typing import List, Optional, Tuple

from app.core.logger import logger
from app.academic_engine.layout_v2.spatial_relationships import BBox, clamp_rect

STRATEGIES = [
    "exact",
    "expand_h",
    "expand_v",
    "shift_down",
    "shift_right",
    "strip_full",
    "contour",
    "zone_full",
]


@dataclass
class CropVariant:
    strategy: str
    image:    np.ndarray        # BGR crop
    bbox:     Optional[BBox]    # (x, y, w, h) within parent zone
    priority: int = 0           # lower = try first

    def __repr__(self) -> str:
        shape = self.image.shape if self.image is not None else None
        return f"CropVariant({self.strategy!r}, shape={shape})"


class AdaptiveCropper:
    """
    Generates multiple alternative crop strategies for a single field ROI.

    Usage:
        cropper = AdaptiveCropper()
        variants = cropper.generate(
            zone_image=summary_zone_bgr,
            anchor_bbox=(x, y, w, h),
            field="percentage",
        )
    """

    def generate(
        self,
        zone_image:   np.ndarray,
        anchor_bbox:  Optional[BBox],
        field:        str = "percentage",
    ) -> List[CropVariant]:
        """
        Generate ranked list of crop alternatives.

        Args:
            zone_image:  BGR zone crop (e.g., summary zone)
            anchor_bbox: (x,y,w,h) inside zone_image for the primary crop
            field:       field name (used for logging)

        Returns:
            Ordered list of CropVariant objects to try in sequence.
        """
        if zone_image is None or zone_image.size == 0:
            return []

        h, w = zone_image.shape[:2]
        variants: List[CropVariant] = []

        # ── Strategy 1: Exact anchor crop ────────────────────────────────────
        if anchor_bbox is not None:
            crop = self._safe_crop(zone_image, anchor_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("exact", crop, anchor_bbox, priority=0))

        # ── Strategy 2: Horizontal expand ────────────────────────────────────
        if anchor_bbox is not None:
            x, y, bw, bh = anchor_bbox
            pad_x = max(30, int(w * 0.12))
            exp_bbox = (max(0, x - pad_x), y, min(w - max(0, x - pad_x), bw + 2 * pad_x), bh)
            crop = self._safe_crop(zone_image, exp_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("expand_h", crop, exp_bbox, priority=1))

        # ── Strategy 3: Vertical expand ──────────────────────────────────────
        if anchor_bbox is not None:
            x, y, bw, bh = anchor_bbox
            pad_y = max(10, int(h * 0.08))
            exp_bbox = (x, max(0, y - pad_y), bw, min(h - max(0, y - pad_y), bh + 2 * pad_y))
            crop = self._safe_crop(zone_image, exp_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("expand_v", crop, exp_bbox, priority=2))

        # ── Strategy 4: Shift down ────────────────────────────────────────────
        if anchor_bbox is not None:
            x, y, bw, bh = anchor_bbox
            shift_y = y + bh // 2
            shift_bbox = (x, min(shift_y, h - bh - 1), bw, bh)
            crop = self._safe_crop(zone_image, shift_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("shift_down", crop, shift_bbox, priority=3))

        # ── Strategy 5: Shift right ───────────────────────────────────────────
        if anchor_bbox is not None:
            x, y, bw, bh = anchor_bbox
            shift_x = x + int(w * 0.15)
            shift_bbox = (min(shift_x, w - bw - 1), y, bw, bh)
            crop = self._safe_crop(zone_image, shift_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("shift_right", crop, shift_bbox, priority=4))

        # ── Strategy 6: Full horizontal strip at anchor y ────────────────────
        if anchor_bbox is not None:
            _, y, _, bh = anchor_bbox
            strip_pad = max(4, bh // 4)
            strip_bbox = (0, max(0, y - strip_pad), w, min(h, bh + strip_pad * 2))
            crop = self._safe_crop(zone_image, strip_bbox, h, w)
            if crop is not None:
                variants.append(CropVariant("strip_full", crop, strip_bbox, priority=5))

        # ── Strategy 7: Largest contour region ───────────────────────────────
        contour_crop = self._contour_crop(zone_image, field)
        if contour_crop is not None:
            variants.append(CropVariant("contour", contour_crop, None, priority=6))

        # ── Strategy 8: Entire zone (maximum fallback) ───────────────────────
        variants.append(CropVariant("zone_full", zone_image.copy(), None, priority=7))

        logger.info("[adaptive_cropper] field=%s generated %d crop variants", field, len(variants))
        return sorted(variants, key=lambda v: v.priority)

    def _safe_crop(
        self, image: np.ndarray, bbox: BBox, img_h: int, img_w: int,
    ) -> Optional[np.ndarray]:
        """Crop with bounds checking. Returns None if area is empty."""
        x, y, bw, bh = bbox
        x1, y1, x2, y2 = clamp_rect((x, y, x + bw, y + bh), img_h, img_w)
        if x2 - x1 < 5 or y2 - y1 < 5:
            return None
        return image[y1:y2, x1:x2].copy()

    def _contour_crop(self, image: np.ndarray, field: str) -> Optional[np.ndarray]:
        """
        Find the largest text-dense connected region in image.
        Useful when the anchor is missing — just find the biggest text blob.
        """
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
            _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            # Dilate to merge nearby text
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 10))
            dilated = cv2.dilate(bw, kernel, iterations=2)
            cnts, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                return None
            # Largest contour
            largest = max(cnts, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            pad = 8
            img_h, img_w = image.shape[:2]
            x1, y1 = max(0, x - pad), max(0, y - pad)
            x2, y2 = min(img_w, x + w + pad), min(img_h, y + h + pad)
            return image[y1:y2, x1:x2].copy()
        except Exception as exc:
            logger.debug("[adaptive_cropper] contour crop failed: %s", exc)
            return None


# Module-level singleton
_cropper = AdaptiveCropper()


def generate_crop_variants(
    zone_image: np.ndarray,
    anchor_bbox: Optional[BBox],
    field: str = "percentage",
) -> List[CropVariant]:
    """Module-level wrapper."""
    return _cropper.generate(zone_image, anchor_bbox, field)
