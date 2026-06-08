"""
app/academic/hsc_summary_extractor.py — HSC Bottom-Region Summary Extractor
=============================================================================
Dedicated extractor for Maharashtra HSC marksheet SUMMARY ROW.

Why a separate module:
  The Maharashtra HSC marksheet stores Percentage and Result in a BOTTOM
  SUMMARY BAND, below all the subject-marks rows.  General full-page OCR
  loses them inside noisy table cells.  This module:

    1. Crops ONLY the bottom 30 % of the document image.
    2. Pre-processes that crop (2x upscale, grayscale, CLAHE, adaptive
       threshold) to maximise Tesseract accuracy.
    3. Runs Tesseract with --psm 6 (uniform block) on the crop.
    4. Searches for Percentage and Result using anchor-right spatial logic
       on the bounding-box data (image_to_data) and, as fallback, plain
       line-regex on the OCR text.
    5. Saves the cropped image to logs/debug_hsc/ for debugging.

ISOLATION:
  Touches ONLY HSC pipeline.  Aadhaar / PAN / SSC / Degree are not affected.
"""

from __future__ import annotations

import os
import re
import logging
from typing import Optional, Tuple, Dict, Any, List

import numpy as np

logger = logging.getLogger("docvalidator")

# ── Debug output directory ─────────────────────────────────────────────────────

_DEBUG_DIR = os.path.join(
    os.path.dirname(__file__),          # .../app/academic/
    "..", "..", "logs", "debug_hsc",    # → backend/logs/debug_hsc/
)
_DEBUG_DIR = os.path.normpath(_DEBUG_DIR)
os.makedirs(_DEBUG_DIR, exist_ok=True)


# ── Image preprocessing helpers ───────────────────────────────────────────────

def _preprocess_crop(crop_arr: np.ndarray) -> np.ndarray:
    """
    Full enhancement pipeline for the bottom summary band:
      1. Upscale 2x (bilinear) for cleaner OCR
      2. Convert to grayscale
      3. CLAHE contrast enhancement
      4. Adaptive threshold (Otsu fallback if CLAHE is flat)
    """
    import cv2

    # 1. Upscale 2×
    h, w = crop_arr.shape[:2]
    crop_arr = cv2.resize(crop_arr, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)

    # 2. Grayscale
    if len(crop_arr.shape) == 3:
        gray = cv2.cvtColor(crop_arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = crop_arr.copy()

    # 3. CLAHE contrast enhancement
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 4. Adaptive threshold — gives clean black text on white
    thresh = cv2.adaptiveThreshold(
        enhanced, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=15,
        C=10,
    )
    return thresh


def _crop_bottom_region(image_arr: np.ndarray, fraction: float = 0.30) -> np.ndarray:
    """
    Returns the bottom `fraction` of the image as a numpy array.
    fraction=0.30 → bottom 30 %.
    """
    h = image_arr.shape[0]
    start_row = int(h * (1.0 - fraction))
    return image_arr[start_row:, :]


def _save_debug_crop(arr: np.ndarray, doc_id: str) -> str:
    """Save cropped (pre-processed) image to logs/debug_hsc/<doc_id>.png."""
    try:
        import cv2
        path = os.path.join(_DEBUG_DIR, f"{doc_id}_bottom_crop.png")
        cv2.imwrite(path, arr)
        logger.info("[HSC SUMMARY OCR] Saved debug crop → %s", path)
        return path
    except Exception as exc:
        logger.warning("[HSC SUMMARY OCR] Could not save debug crop: %s", exc)
        return ""


# ── OCR on crop ───────────────────────────────────────────────────────────────

def _ocr_crop_with_boxes(arr: np.ndarray) -> Tuple[str, List[Dict]]:
    """
    Run Tesseract --psm 6 on the pre-processed crop.
    Returns (full_text, list_of_word_boxes).

    Each box: {"text": str, "left": int, "top": int, "width": int, "height": int, "conf": int}
    """
    try:
        # import pytesseract
        from PIL import Image as PILImage

        pil_img = PILImage.fromarray(arr)

        # Full text (for line-level regex fallback)
        text = pytesseract.image_to_string(
            pil_img,
            config="--oem 3 --psm 6",
            lang="eng",
        )

        # Bounding-box data for spatial anchor extraction
        raw_data = pytesseract.image_to_data(
            pil_img,
            config="--oem 3 --psm 6",
            lang="eng",
            output_type=pytesseract.Output.DICT,
        )

        boxes: List[Dict] = []
        n = len(raw_data["text"])
        for i in range(n):
            word = (raw_data["text"][i] or "").strip()
            conf = int(raw_data["conf"][i])
            if word and conf >= 0:
                boxes.append({
                    "text":   word,
                    "left":   raw_data["left"][i],
                    "top":    raw_data["top"][i],
                    "width":  raw_data["width"][i],
                    "height": raw_data["height"][i],
                    "conf":   conf,
                })

        logger.info(
            "[HSC SUMMARY OCR] Crop OCR done: %d chars, %d word-boxes",
            len(text), len(boxes),
        )
        return text.strip(), boxes

    except Exception as exc:
        logger.error("[HSC SUMMARY OCR] Tesseract failed on crop: %s", exc)
        return "", []


# ── Spatial anchor extraction ─────────────────────────────────────────────────

_PCT_VALUE_RE = re.compile(r"\b(\d{2}\.\d{2})\b")   # e.g. 75.17
_PCT_PCT_RE   = re.compile(r"\b(\d{2,3})%")           # e.g. 65%
_RESULT_KEYWORDS = re.compile(
    r"\b(PASS|PASSED|FAIL|FAILED|DISTINCTION|FIRST\s+CLASS|SECOND\s+CLASS|THIRD\s+CLASS)\b",
    re.IGNORECASE,
)


def _nearest_right_value(
    anchor_word: str,
    boxes: List[Dict],
    same_row_tolerance_px: int = 40,
) -> Optional[str]:
    """
    Find the bounding box whose text matches `anchor_word` (case-insensitive).
    Then return the text of the nearest box to the RIGHT on the same row.

    Same-row = top coordinates within `same_row_tolerance_px` pixels.
    """
    anchor_box = None
    for box in boxes:
        if re.search(re.escape(anchor_word), box["text"], re.IGNORECASE):
            anchor_box = box
            break

    if anchor_box is None:
        return None

    anchor_top    = anchor_box["top"]
    anchor_right  = anchor_box["left"] + anchor_box["width"]

    candidates = []
    for box in boxes:
        if abs(box["top"] - anchor_top) <= same_row_tolerance_px:
            if box["left"] > anchor_right:
                candidates.append(box)

    if not candidates:
        return None

    # Nearest right
    candidates.sort(key=lambda b: b["left"])
    return candidates[0]["text"]


def _extract_percentage_spatial(boxes: List[Dict]) -> Optional[float]:
    """
    Strategy 1 — spatial: find 'Percentage' anchor, grab right neighbour.
    Strategy 2 — scan all boxes for dd.dd pattern in range [35, 100].
    """
    # Strategy 1: anchor → right
    for anchor in ("Percentage", "टक्केवारी", "%"):
        raw = _nearest_right_value(anchor, boxes)
        if raw:
            m = _PCT_VALUE_RE.search(raw)
            if m:
                val = float(m.group(1))
                if 35.0 <= val <= 100.0:
                    logger.info("[HSC PERCENTAGE DETECTED] spatial anchor '%s' → %s", anchor, val)
                    return round(val, 2)

    # Strategy 2: scan all box texts for decimal percentage
    candidates: List[float] = []
    for box in boxes:
        m = _PCT_VALUE_RE.search(box["text"])
        if m:
            val = float(m.group(1))
            if 35.0 <= val <= 100.0:
                candidates.append(val)

    if candidates:
        # Prefer the first one found (top-to-bottom order)
        val = candidates[0]
        logger.info("[HSC PERCENTAGE DETECTED] scan fallback → %s", val)
        return round(val, 2)

    return None


def _extract_result_spatial(boxes: List[Dict], full_text: str) -> Optional[str]:
    """
    Strategy 1 — spatial: find 'Result' or 'निकाल' anchor, grab right neighbour.
    Strategy 2 — scan boxes for result keywords.
    Strategy 3 — regex on full text.
    """
    _RESULT_NORM = {
        "pass":        "PASS",
        "passed":      "PASS",
        "fail":        "FAIL",
        "failed":      "FAIL",
        "distinction": "DISTINCTION",
        "first":       "FIRST CLASS",   # "first class" — partial
        "second":      "SECOND CLASS",
        "third":       "THIRD CLASS",
    }

    def _normalise(raw: str) -> Optional[str]:
        low = raw.strip().lower()
        for key, label in _RESULT_NORM.items():
            if re.search(rf"\b{key}\b", low):
                return label
        return None

    # Strategy 1: anchor → right
    for anchor in ("Result", "निकाल", "RESULT"):
        raw = _nearest_right_value(anchor, boxes, same_row_tolerance_px=50)
        if raw:
            norm = _normalise(raw)
            if norm:
                logger.info("[HSC RESULT DETECTED] spatial anchor '%s' → %s", anchor, norm)
                return norm

    # Strategy 2: scan boxes in top-to-bottom order for result keywords
    sorted_boxes = sorted(boxes, key=lambda b: (b["top"], b["left"]))
    for box in sorted_boxes:
        norm = _normalise(box["text"])
        if norm:
            logger.info("[HSC RESULT DETECTED] box scan → %s (raw='%s')", norm, box["text"])
            return norm

    # Strategy 3: full text regex
    m = _RESULT_KEYWORDS.search(full_text)
    if m:
        norm = _normalise(m.group(0))
        logger.info("[HSC RESULT DETECTED] full-text regex → %s", norm)
        return norm

    return None


# ── Line-regex fallback (when boxes are empty) ────────────────────────────────

def _extract_percentage_from_lines(text: str) -> Optional[float]:
    """
    Scan lines of the summary crop text for percentage anchors.
    Only searches for dd.dd decimal values in [35, 100].
    """
    lines = text.splitlines()
    # First pass: lines containing 'percentage' keyword
    for line in lines:
        if re.search(r"percentage|टक्केवारी|%", line, re.IGNORECASE):
            m = _PCT_VALUE_RE.search(line)
            if m:
                val = float(m.group(1))
                if 35.0 <= val <= 100.0:
                    logger.info("[HSC PERCENTAGE DETECTED] line-regex → %s", val)
                    return round(val, 2)
    # Second pass: any decimal in range across all lines
    for line in lines:
        for m in _PCT_VALUE_RE.finditer(line):
            val = float(m.group(1))
            if 35.0 <= val <= 100.0:
                logger.info("[HSC PERCENTAGE DETECTED] fallback decimal scan → %s", val)
                return round(val, 2)
    return None


def _extract_result_from_lines(text: str) -> Optional[str]:
    """
    Scan lines for result keywords.  Only looks near 'Result'/'निकाल' first.
    """
    lines = text.splitlines()
    _MAP = [
        (r"\bpass(ed)?\b",       "PASS"),
        (r"\bfail(ed)?\b",       "FAIL"),
        (r"\bdistinction\b",     "DISTINCTION"),
        (r"\bfirst\s+class\b",   "FIRST CLASS"),
        (r"\bsecond\s+class\b",  "SECOND CLASS"),
    ]
    # Near result anchor first
    for line in lines:
        if re.search(r"result|निकाल", line, re.IGNORECASE):
            for pat, label in _MAP:
                if re.search(pat, line, re.IGNORECASE):
                    logger.info("[HSC RESULT DETECTED] line-anchor → %s", label)
                    return label
    # Standalone scan
    for line in lines:
        for pat, label in _MAP:
            if re.search(pat, line, re.IGNORECASE):
                logger.info("[HSC RESULT DETECTED] standalone scan → %s", label)
                return label
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

def extract_hsc_summary(
    image_arr: np.ndarray,
    doc_id: str = "hsc",
    bottom_fraction: float = 0.30,
) -> Dict[str, Any]:
    """
    Main entry point.

    Args:
        image_arr:       Full document image as H×W×3 uint8 RGB numpy array.
        doc_id:          Unique ID used for debug-image filename.
        bottom_fraction: Fraction of image height to crop from the bottom.
                         Default 0.30 = bottom 30 %.

    Returns:
        {
          "percentage": float | None,
          "result":     str   | None,
          "debug_crop_path": str,
        }
    """
    logger.info(
        "[HSC SUMMARY OCR] Starting bottom-region extraction (%.0f%% crop) for doc_id=%s",
        bottom_fraction * 100, doc_id,
    )

    # 1. Crop bottom fraction
    crop_raw = _crop_bottom_region(image_arr, fraction=bottom_fraction)

    # 2. Preprocess
    try:
        crop_proc = _preprocess_crop(crop_raw)
    except Exception as exc:
        logger.warning("[HSC SUMMARY OCR] Preprocess failed (%s), using raw crop", exc)
        crop_proc = crop_raw

    # 3. Save debug image
    debug_path = _save_debug_crop(crop_proc, doc_id)

    # 4. OCR the processed crop
    ocr_text, boxes = _ocr_crop_with_boxes(crop_proc)

    logger.debug("[HSC SUMMARY OCR] Crop OCR text:\n%s", ocr_text)

    # 5. Extract percentage
    if boxes:
        percentage = _extract_percentage_spatial(boxes)
    else:
        percentage = None

    if percentage is None:
        # Fallback to line regex on crop text
        percentage = _extract_percentage_from_lines(ocr_text)

    # 6. Extract result
    if boxes:
        result = _extract_result_spatial(boxes, ocr_text)
    else:
        result = None

    if result is None:
        result = _extract_result_from_lines(ocr_text)

    logger.info(
        "[HSC SUMMARY OCR] Final → percentage=%s  result=%s",
        percentage, result,
    )

    return {
        "percentage":      percentage,
        "result":          result,
        "debug_crop_path": debug_path,
        "crop_ocr_text":   ocr_text,
    }
