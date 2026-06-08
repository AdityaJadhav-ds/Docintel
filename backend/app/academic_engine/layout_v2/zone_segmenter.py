"""
academic_engine/layout_v2/zone_segmenter.py
============================================
Content-adaptive document zone segmentation (replaces fraction-only slicing).

Zones:
  ZONE_A  HEADER        — board/university/title/exam-type
  ZONE_B  CANDIDATE     — name, seat/PRN, stream
  ZONE_C  SUBJECT_TABLE — marks rows (noise for extraction, should be masked)
  ZONE_D  SUMMARY       — percentage / CGPA / result / class ← MOST IMPORTANT
  ZONE_E  NOISE         — QR codes, holograms, signatures, stamps

Strategy:
  1. Classify layout variant (SSC / HSC / Degree / Certificate / Diploma)
  2. Use variant-specific seed fractions as STARTING candidates
  3. Refine each zone boundary using content signals:
       - table bounding box  → precise SUBJECT_TABLE zone
       - text density profile → shift header/candidate boundary
       - QR detection        → mark NOISE zone precisely
  4. Return dict of zone_name → {bbox, crop, metadata}
"""

from __future__ import annotations

import re
import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.core.logger import logger
from app.academic_engine.layout_v2.spatial_relationships import (
    clamp_rect, fraction_crop, Rect, BBox
)
from app.academic_engine.layout_v2.layout_classifier import LayoutVariant, classify_layout
from app.academic_engine.layout_v2.table_detector import detect_table, TableDetectionResult


# ── Border-trim helper ────────────────────────────────────────────────────

def _trim_background_borders(img: np.ndarray, threshold: float = 0.015) -> np.ndarray:
    """
    Remove background margins ONLY when the image has clearly bright/white borders
    (i.e. scanned documents). Skips mobile photos with dark/patterned backgrounds.
    """
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()
        h, w = gray.shape

        # Sample border pixels (5% margin on each edge)
        bw  = int(w * 0.05)
        bh  = int(h * 0.05)
        top    = gray[:bh, :].mean()
        bottom = gray[h-bh:, :].mean()
        left   = gray[:, :bw].mean()
        right  = gray[:, w-bw:].mean()
        border_mean = (top + bottom + left + right) / 4

        # Only trim if borders are bright (scanned doc = white background)
        # Mobile photos on beds/tables have dark/mixed borders — skip
        if border_mean < 200:
            logger.debug(
                "[zone_segmenter] Border trim skipped (dark border mean=%.0f, likely mobile photo)",
                border_mean,
            )
            return img

        _, bw_mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        row_density = bw_mask.mean(axis=1) / 255.0
        col_density = bw_mask.mean(axis=0) / 255.0

        rows_with_text = np.where(row_density > threshold)[0]
        cols_with_text = np.where(col_density > threshold)[0]

        if len(rows_with_text) < 10 or len(cols_with_text) < 10:
            return img

        r0, r1 = int(rows_with_text[0]),  int(rows_with_text[-1])
        c0, c1 = int(cols_with_text[0]),  int(cols_with_text[-1])

        pad_r, pad_c = max(5, h // 50), max(5, w // 50)
        r0 = max(0,  r0 - pad_r); r1 = min(h, r1 + pad_r)
        c0 = max(0,  c0 - pad_c); c1 = min(w, c1 + pad_c)

        crop_area = (r1 - r0) * (c1 - c0)
        orig_area = h * w
        if crop_area < orig_area * 0.6:
            logger.info("[zone_segmenter] Border trim skipped — would remove too much")
            return img

        trimmed = img[r0:r1, c0:c1]
        logger.info("[zone_segmenter] Border trim applied: %dx%d -> %dx%d (border_mean=%.0f)",
                    w, h, trimmed.shape[1], trimmed.shape[0], border_mean)
        return trimmed
    except Exception as exc:
        logger.debug("[zone_segmenter] Border trim failed: %s", exc)
        return img


# ── Landmark helpers ────────────────────────────────────────────────────

_NAME_LABEL_RE = re.compile(
    r"candidate.{0,20}(?:full\s+)?name"
    r"|student.{0,10}name"
    r"|full\s+name"
    r"|name\s+of.{0,15}(?:candidate|student)"
    r"|\bsurname\s+first\b"
    r"|उमेदवाराचे.{0,10}नाव"
    r"|विद्यार्थ्याचे.{0,10}नाव",
    re.IGNORECASE,
)


def _find_name_label_y(ocr_text: str, image_h: int) -> Optional[int]:
    """
    Try to locate the y-pixel of the 'CANDIDATE'S FULL NAME' label in the document
    by searching the full-page OCR text. Returns pixel y if found, else None.

    Since we don't have per-line bboxes from classification OCR, we use the
    relative line position within the OCR output as a fraction of image height.
    """
    lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    if not lines:
        return None
    for idx, line in enumerate(lines):
        if _NAME_LABEL_RE.search(line):
            frac = idx / max(len(lines), 1)
            # Name label is typically in top 35% of page
            if frac < 0.5:
                y_estimate = int(frac * image_h)
                logger.info("[zone_segmenter] Name label found at line %d/%d → y~%d",
                            idx, len(lines), y_estimate)
                return y_estimate
    return None



# ── Zone names ────────────────────────────────────────────────────────────────

ZONE_HEADER    = "header"
ZONE_CANDIDATE = "candidate"
ZONE_SUBJECTS  = "subjects"
ZONE_SUMMARY   = "summary"
ZONE_NOISE     = "noise"

EXTRACTION_ZONES = [ZONE_HEADER, ZONE_CANDIDATE, ZONE_SUMMARY]
IGNORED_ZONES    = [ZONE_SUBJECTS, ZONE_NOISE]


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ZoneInfo:
    name:       str
    label:      str
    rect:       Rect                         # (x1,y1,x2,y2) absolute pixels
    crop:       Optional[np.ndarray] = None  # BGR crop of the zone
    enabled:    bool = True
    confidence: float = 1.0
    metadata:   Dict = field(default_factory=dict)

    @property
    def bbox(self) -> BBox:
        x1, y1, x2, y2 = self.rect
        return (x1, y1, x2 - x1, y2 - y1)

    def __repr__(self) -> str:
        x1, y1, x2, y2 = self.rect
        return (
            f"ZoneInfo({self.name!r}, rect=({x1},{y1})→({x2},{y2}), "
            f"enabled={self.enabled}, conf={self.confidence:.2f})"
        )


SegmentationResult = Dict[str, ZoneInfo]


# ── QR detection helper ───────────────────────────────────────────────────────

def _detect_qr_bbox(gray: np.ndarray) -> Optional[BBox]:
    """Detect first QR code in image, return its bbox or None."""
    try:
        detector = cv2.QRCodeDetector()
        _, pts   = detector.detect(gray)
        if pts is not None and len(pts) > 0:
            x, y, w, h = cv2.boundingRect(pts[0].astype(np.int32))
            pad = 20
            img_h, img_w = gray.shape[:2]
            return (
                max(0, x - pad), max(0, y - pad),
                min(img_w, x + w + pad) - max(0, x - pad),
                min(img_h, y + h + pad) - max(0, y - pad),
            )
    except Exception:
        pass
    return None


# ── Text density profile ──────────────────────────────────────────────────────

def _text_density_profile(gray: np.ndarray, bins: int = 40) -> np.ndarray:
    """
    Compute horizontal text density profile (fraction of dark pixels per row-band).
    Returns array of shape (bins,) with values 0.0–1.0.
    """
    h, w = gray.shape
    band_h = max(1, h // bins)
    profile = np.zeros(bins, dtype=np.float32)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    for i in range(bins):
        y0 = i * band_h
        y1 = min(h, (i + 1) * band_h)
        band = bw[y0:y1, :]
        profile[i] = float(band.sum()) / (255 * band.size) if band.size > 0 else 0
    return profile


def _find_low_density_boundary(
    profile: np.ndarray,
    search_start_bin: int,
    search_end_bin: int,
    threshold: float = 0.02,
) -> Optional[int]:
    """
    Find first bin in [search_start, search_end] where density drops below threshold.
    Returns bin index or None.
    """
    for i in range(search_start_bin, min(search_end_bin, len(profile))):
        if profile[i] < threshold:
            return i
    return None


# ── Main segmenter ────────────────────────────────────────────────────────────

class ZoneSegmenter:
    """
    Content-adaptive document zone segmenter.

    Usage:
        segmenter = ZoneSegmenter()
        result    = segmenter.segment(image, ocr_text)
        summary_crop = result["summary"].crop
    """

    def segment(
        self,
        image:    np.ndarray,
        ocr_text: str = "",
    ) -> SegmentationResult:
        """
        Segment document image into named zones.

        Args:
            image:    BGR restored document image (numpy array)
            ocr_text: Optional preliminary OCR text for layout classification.

        Returns:
            Dict of zone_name → ZoneInfo
        """
        if image is None or image.size == 0:
            logger.warning("[zone_segmenter] Empty image")
            return {}

        h, w = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        logger.info("[zone_segmenter] Image: %dx%d", w, h)

        # ── Step 0: Strip background/sleeve borders ────────────────────────
        image = _trim_background_borders(image)
        if image.shape[:2] != (h, w):
            h, w = image.shape[:2]
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            logger.info("[zone_segmenter] After trim: %dx%d", w, h)

        # ── Step 1: Classify layout variant ─────────────────────────────
        variant: LayoutVariant = classify_layout(ocr_text, img=image)
        logger.info("[zone_segmenter] Layout variant: %s", variant.layout_class)

        # ── Step 2: Detect table and QR ──────────────────────────────────
        table_result: TableDetectionResult = detect_table(image)
        qr_bbox: Optional[BBox]            = _detect_qr_bbox(gray)
        density_profile = _text_density_profile(gray, bins=50)

        # ── Step 3: Derive zone rects ───────────────────────────────────
        zones: SegmentationResult = {}

        # ZONE A — Header
        header_rect = self._compute_header_rect(
            h, w, variant, density_profile
        )
        zones[ZONE_HEADER] = ZoneInfo(
            name    = ZONE_HEADER,
            label   = "Zone A — Header (Board / Title)",
            rect    = header_rect,
            enabled = True,
        )

        # ZONE B — Candidate
        candidate_rect = self._compute_candidate_rect(
            h, w, variant, header_rect, table_result, ocr_text=ocr_text
        )
        zones[ZONE_CANDIDATE] = ZoneInfo(
            name    = ZONE_CANDIDATE,
            label   = "Zone B — Candidate Info (Name / Seat No)",
            rect    = candidate_rect,
            enabled = True,
        )

        # ZONE C — Subject table (disabled for extraction)
        subject_rect = self._compute_subjects_rect(
            h, w, variant, table_result
        )
        zones[ZONE_SUBJECTS] = ZoneInfo(
            name    = ZONE_SUBJECTS,
            label   = "Zone C — Subject Table (Ignored)",
            rect    = subject_rect,
            enabled = False,  # NEVER extract from here
            metadata= {"table_detected": table_result.found},
        )

        # ZONE D — Summary / Result (MOST IMPORTANT)
        summary_rect = self._compute_summary_rect(
            h, w, variant, table_result, qr_bbox, density_profile
        )
        zones[ZONE_SUMMARY] = ZoneInfo(
            name    = ZONE_SUMMARY,
            label   = "Zone D — Summary / Result (% / CGPA / Pass)",
            rect    = summary_rect,
            enabled = True,
            confidence = 0.9,
        )

        # ZONE E — Noise (QR / hologram)
        noise_rect = self._compute_noise_rect(h, w, variant, qr_bbox)
        zones[ZONE_NOISE] = ZoneInfo(
            name    = ZONE_NOISE,
            label   = "Zone E — Noise (QR / Hologram / Stamp)",
            rect    = noise_rect,
            enabled = False,  # NEVER extract from here
            metadata= {"qr_detected": qr_bbox is not None},
        )

        # ── Step 4: Crop each zone ────────────────────────────────────────────
        for zone in zones.values():
            x1, y1, x2, y2 = clamp_rect(zone.rect, h, w)
            if x2 > x1 and y2 > y1:
                zone.crop = image[y1:y2, x1:x2].copy()
                zone.rect = (x1, y1, x2, y2)
            else:
                zone.crop = None
                zone.enabled = False

        self._log_zones(zones)
        return zones

    # ── Zone boundary computations ────────────────────────────────────────────

    def _compute_header_rect(
        self,
        h: int, w: int,
        variant: LayoutVariant,
        profile: np.ndarray,
    ) -> Rect:
        """Header: top of image to just below the title/logo block."""
        seed_end_y = int(variant.header_frac * h)
        # Try to refine: find low-density gap after the header text block
        bins_per_pixel = len(profile) / h
        search_start = int(0.08 * len(profile))
        search_end   = int(variant.header_frac * len(profile)) + 5
        low_bin = _find_low_density_boundary(profile, search_start, search_end)
        if low_bin is not None:
            refined_y = int(low_bin / bins_per_pixel) + 5
            seed_end_y = max(seed_end_y, refined_y)
        return clamp_rect((0, 0, w, seed_end_y), h, w)

    def _compute_candidate_rect(
        self,
        h: int, w: int,
        variant: LayoutVariant,
        header_rect: Rect,
        table_result: TableDetectionResult,
        ocr_text: str = "",
    ) -> Rect:
        """Candidate: below header, above subject table, guaranteed to span name label."""
        y_start = header_rect[3]  # always start at header bottom

        # Guard: if table covers >80% of image it's a detection failure, use fraction
        table_sane = (
            table_result.found
            and table_result.bbox is not None
            and (table_result.bbox[3] / h) < 0.80   # table height < 80% of image
            and table_result.bbox[1] > int(h * 0.20) # table top > 20% down
        )
        if table_sane:
            y_end = table_result.bbox[1]  # top of detected table
        else:
            y_end = int(variant.candidate_frac[1] * h)

        # Enforce minimum candidate height
        min_height = max(80, int(h * 0.08))
        if y_end - y_start < min_height:
            y_end = y_start + min_height

        # Extend past name label so the actual name line is captured
        name_label_y = _find_name_label_y(ocr_text, h)
        if name_label_y is not None:
            label_end = name_label_y + 80
            if label_end > y_end:
                y_end = label_end

        logger.info("[zone_segmenter] Candidate rect: y=%d->%d (h=%d, table_sane=%s, landmark=%s)",
                    y_start, y_end, y_end - y_start, table_sane, name_label_y is not None)
        return clamp_rect((0, y_start, w, y_end), h, w)

    def _compute_subjects_rect(
        self,
        h: int, w: int,
        variant: LayoutVariant,
        table_result: TableDetectionResult,
    ) -> Rect:
        """Subject table: use detected table bbox if found and sane, else fraction."""
        table_sane = (
            table_result.found
            and table_result.bbox is not None
            and (table_result.bbox[3] / h) < 0.80
            and table_result.bbox[1] > int(h * 0.15)
        )
        if table_sane:
            bx, by, bw, bh = table_result.bbox
            return clamp_rect((bx, by, bx + bw, by + bh), h, w)
        s0 = int(variant.subject_frac[0] * h)
        s1 = int(variant.subject_frac[1] * h)
        return clamp_rect((0, s0, w, s1), h, w)

    def _compute_summary_rect(
        self,
        h: int, w: int,
        variant: LayoutVariant,
        table_result: TableDetectionResult,
        qr_bbox: Optional[BBox],
        profile: np.ndarray,
    ) -> Rect:
        """
        Summary: below subject table, above QR/noise.
        MOST CRITICAL zone — guarded against full-image table detection failure.
        """
        # Guard: only use table bottom if table detection is sane
        table_sane = (
            table_result.found
            and table_result.bbox is not None
            and (table_result.bbox[3] / h) < 0.80
            and table_result.bbox[1] > int(h * 0.15)
        )
        if table_sane:
            y_start = table_result.bbox[1] + table_result.bbox[3]  # bottom of table
        else:
            y_start = int(variant.summary_frac[0] * h)

        # End: above QR or noise zone
        if qr_bbox is not None:
            y_end = qr_bbox[1] - 5
        else:
            y_end = int(variant.noise_frac_start * h)

        # Safety clamps
        y_start = max(0, min(y_start, h - 100))
        y_end   = max(y_start + 80, min(y_end, h))

        # Extend end if summary is too short (< 6% image height)
        min_summary_h = max(80, int(h * 0.06))
        if y_end - y_start < min_summary_h:
            y_end = min(h, y_start + min_summary_h)

        # Find first text-dense bin to tighten y_start
        bins_per_pixel = len(profile) / h
        start_bin = int(y_start * bins_per_pixel)
        end_bin   = int(y_end   * bins_per_pixel)
        for i in range(start_bin, min(end_bin, len(profile))):
            if profile[i] > 0.01:
                y_start = max(y_start, int(i / bins_per_pixel) - 5)
                break

        logger.info(
            "[zone_segmenter] Summary rect: y=%d->%d (%.0f%%->%.0f%% H, table_sane=%s)",
            y_start, y_end, 100*y_start/h, 100*y_end/h, table_sane,
        )
        return clamp_rect((0, y_start, w, y_end), h, w)

    def _compute_noise_rect(
        self,
        h: int, w: int,
        variant: LayoutVariant,
        qr_bbox: Optional[BBox],
    ) -> Rect:
        """Noise zone: bottom of image, including QR area."""
        if qr_bbox is not None:
            y_start = max(0, qr_bbox[1] - 10)
        else:
            y_start = int(variant.noise_frac_start * h)
        return clamp_rect((0, y_start, w, h), h, w)

    # ── Logging ───────────────────────────────────────────────────────────────

    @staticmethod
    def _log_zones(zones: SegmentationResult) -> None:
        for name, zone in zones.items():
            x1, y1, x2, y2 = zone.rect
            shape = f"{zone.crop.shape[1]}×{zone.crop.shape[0]}" if zone.crop is not None else "None"
            logger.info(
                "[zone_segmenter] %-12s enabled=%-5s rect=(%d,%d)→(%d,%d) crop=%s",
                name, zone.enabled, x1, y1, x2, y2, shape,
            )


# ── Module-level singleton ────────────────────────────────────────────────────

_segmenter = ZoneSegmenter()


def segment_document(
    image: np.ndarray,
    ocr_text: str = "",
) -> SegmentationResult:
    """Module-level convenience wrapper."""
    return _segmenter.segment(image, ocr_text=ocr_text)
