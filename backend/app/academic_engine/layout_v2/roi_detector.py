"""
academic_engine/layout_v2/roi_detector.py
==========================================
Per-field ROI Detector — the bridge between zone segmentation and OCR.

Takes zone crops from zone_segmenter and produces field-specific
sub-ROIs with dedicated preprocessing for each field type.

ROI Types and their strategies:

  NAME ROI
    preprocessing: mild sharpen + contrast normalize
    ocr_config:    --psm 7 (single line)
    validation:    alpha + spaces only, 4–60 chars

  PERCENTAGE ROI
    preprocessing: CLAHE + upscale 4× + adaptive threshold + morph close
    ocr_config:    --psm 7 --oem 3 + digit whitelist "0123456789.%"
    validation:    0.0–100.0

  CGPA ROI
    preprocessing: similar to percentage
    ocr_config:    --psm 7 + whitelist "0123456789."
    validation:    0.0–10.0

  RESULT ROI
    preprocessing: contrast boost + denoising
    ocr_config:    --psm 7 + whitelist "ABCDEFGHIJKLMNOPQRSTUVWXYZ "
    validation:    known result strings

  HEADER ROI
    preprocessing: mild enhance
    ocr_config:    --psm 6 (block)
    validation:    none

  SUMMARY ROI (generic fallback)
    preprocessing: CLAHE + slight upscale
    ocr_config:    --psm 6
    validation:    none
"""

from __future__ import annotations

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.core.logger import logger
from app.academic_engine.layout_v2.zone_segmenter import ZoneInfo, SegmentationResult

# ── ROI preprocessing strategies ─────────────────────────────────────────────

def _preprocess_name(roi: np.ndarray) -> np.ndarray:
    """Mild sharpen + contrast normalise for clean name text."""
    gray  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    # Upscale if small
    h, w = gray.shape
    if w < 400:
        gray = cv2.resize(gray, (int(w * 2), int(h * 2)), interpolation=cv2.INTER_LANCZOS4)
    # CLAHE
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    # Mild unsharp mask
    blur  = cv2.GaussianBlur(gray, (0, 0), 1.0)
    gray  = cv2.addWeighted(gray, 1.4, blur, -0.4, 0)
    return gray


def _preprocess_percentage(roi: np.ndarray) -> np.ndarray:
    """
    Heavy preprocessing for percentage / CGPA ROIs.
    Upscale → CLAHE → adaptive threshold → morphological close.
    """
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

    # Step 1: Upscale 4× for digit clarity
    h, w = gray.shape
    scale = max(4, 600 // max(w, 1))
    gray  = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)

    # Step 2: CLAHE
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    gray  = clahe.apply(gray)

    # Step 3: Adaptive threshold (binarise)
    bw = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15, C=4,
    )

    # Step 4: Morphological close (join broken strokes)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    bw     = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, kernel)

    return bw


def _preprocess_result(roi: np.ndarray) -> np.ndarray:
    """Contrast boost + CLAHE for PASS/FAIL/DISTINCTION text."""
    gray  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w  = gray.shape
    if w < 300:
        gray = cv2.resize(gray, (int(w * 2.5), int(h * 2.5)), interpolation=cv2.INTER_LANCZOS4)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray  = clahe.apply(gray)
    # Threshold to binary
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def _preprocess_header(roi: np.ndarray) -> np.ndarray:
    """Mild enhance for multi-line header block."""
    gray  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w  = gray.shape
    if w < 500:
        gray = cv2.resize(gray, (int(w * 1.5), int(h * 1.5)), interpolation=cv2.INTER_LANCZOS4)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _preprocess_summary_generic(roi: np.ndarray) -> np.ndarray:
    """Generic summary zone preprocessing."""
    gray  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    h, w  = gray.shape
    if w < 600:
        scale = 600 / w
        gray  = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    return clahe.apply(gray)


# ── OCR config per field ──────────────────────────────────────────────────────

OCR_CONFIGS: Dict[str, str] = {
    "name":        "--oem 3 --psm 7",
    "percentage":  "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.%",
    "cgpa":        "--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.",
    "result":      "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ ",
    "grade_class": "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ+- ",
    "header":      "--oem 3 --psm 6",
    "summary":     "--oem 3 --psm 6",
    "candidate":   "--oem 3 --psm 6",
}


# ── ROI spec ──────────────────────────────────────────────────────────────────

@dataclass
class ROISpec:
    field:      str
    source_zone: str          # which zone crop this came from
    preprocessed: Optional[np.ndarray]
    raw_crop:   Optional[np.ndarray]
    ocr_config: str
    confidence: float = 1.0


# ── Detector ──────────────────────────────────────────────────────────────────

class ROIDetector:
    """
    Produces field-specific preprocessed ROIs from zone crops.
    """

    def extract_rois(
        self,
        zones: SegmentationResult,
        summary_locator_result=None,  # SummaryLocatorResult | None
    ) -> Dict[str, ROISpec]:
        """
        Build ROISpecs for all extraction fields.

        Args:
            zones:                  Result from ZoneSegmenter.segment()
            summary_locator_result: Optional result from SummaryLocator.locate()
                                    If provided, use its precise sub-ROIs for
                                    percentage/CGPA/result.

        Returns:
            Dict of field_name → ROISpec
        """
        rois: Dict[str, ROISpec] = {}

        # ── Header ────────────────────────────────────────────────────────────
        header_zone = zones.get("header")
        if header_zone and header_zone.crop is not None:
            rois["header"] = ROISpec(
                field        = "header",
                source_zone  = "header",
                preprocessed = _preprocess_header(header_zone.crop),
                raw_crop     = header_zone.crop,
                ocr_config   = OCR_CONFIGS["header"],
            )

        # ── Candidate (name, seat no) ──────────────────────────────────────────
        cand_zone = zones.get("candidate")
        if cand_zone and cand_zone.crop is not None:
            rois["candidate"] = ROISpec(
                field        = "candidate",
                source_zone  = "candidate",
                preprocessed = _preprocess_name(cand_zone.crop),
                raw_crop     = cand_zone.crop,
                ocr_config   = OCR_CONFIGS["candidate"],
            )

        # ── Summary (fallback full zone) ───────────────────────────────────────
        summary_zone = zones.get("summary")
        if summary_zone and summary_zone.crop is not None:
            rois["summary"] = ROISpec(
                field        = "summary",
                source_zone  = "summary",
                preprocessed = _preprocess_summary_generic(summary_zone.crop),
                raw_crop     = summary_zone.crop,
                ocr_config   = OCR_CONFIGS["summary"],
            )

        # ── Precise ROIs from SummaryLocator ──────────────────────────────────
        if summary_locator_result is not None:
            slr = summary_locator_result

            if slr.percentage_roi and slr.percentage_roi.roi is not None:
                rois["percentage"] = ROISpec(
                    field        = "percentage",
                    source_zone  = "summary",
                    preprocessed = _preprocess_percentage(slr.percentage_roi.roi),
                    raw_crop     = slr.percentage_roi.roi,
                    ocr_config   = OCR_CONFIGS["percentage"],
                    confidence   = slr.percentage_roi.confidence,
                )

            if slr.cgpa_roi and slr.cgpa_roi.roi is not None:
                rois["cgpa"] = ROISpec(
                    field        = "cgpa",
                    source_zone  = "summary",
                    preprocessed = _preprocess_percentage(slr.cgpa_roi.roi),
                    raw_crop     = slr.cgpa_roi.roi,
                    ocr_config   = OCR_CONFIGS["cgpa"],
                    confidence   = slr.cgpa_roi.confidence,
                )

            if slr.result_roi and slr.result_roi.roi is not None:
                rois["result"] = ROISpec(
                    field        = "result",
                    source_zone  = "summary",
                    preprocessed = _preprocess_result(slr.result_roi.roi),
                    raw_crop     = slr.result_roi.roi,
                    ocr_config   = OCR_CONFIGS["result"],
                    confidence   = slr.result_roi.confidence,
                )

        self._log_rois(rois)
        return rois

    @staticmethod
    def _log_rois(rois: Dict[str, ROISpec]) -> None:
        for field, roi_spec in rois.items():
            shape = (
                roi_spec.preprocessed.shape
                if roi_spec.preprocessed is not None else None
            )
            logger.info(
                "[roi_detector] %-15s zone=%-12s shape=%s conf=%.2f",
                field, roi_spec.source_zone, shape, roi_spec.confidence,
            )


# ── Singleton ─────────────────────────────────────────────────────────────────
_detector = ROIDetector()


def extract_rois(
    zones: SegmentationResult,
    summary_locator_result=None,
) -> Dict[str, ROISpec]:
    """Module-level wrapper."""
    return _detector.extract_rois(zones, summary_locator_result)
