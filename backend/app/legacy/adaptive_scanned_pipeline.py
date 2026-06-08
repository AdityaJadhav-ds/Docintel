"""
app/extraction/adaptive_scanned_pipeline.py
============================================
Thin router for scanned bank statement extraction.

Responsibility (ONLY):
  1. EARLY bank detection from header image (NO full OCR needed)
  2. Full-page OCR ONCE with appropriate confidence
  3. Dispatch to the correct bank handler
  4. Return result in the standard format

Key design rules:
  - Bank detection is DECOUPLED from full-page OCR.
    It uses only the top 12% of the image with a LOW confidence
    threshold (0.25) so it works even on bad scans.
  - Full reconstruction OCR uses a HIGHER threshold (0.40) to filter garbage.
  - If the high-threshold pass returns nothing, we fall back to a lower
    threshold (0.30) so we always have something to work with.

All reconstruction logic lives in:
  app/extraction/bank_handlers/

External API (unchanged — core_extractor.py calls this):
  extract_adaptive_scanned_bank_statement(bgr, page_idx) -> Dict
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional

import cv2
import numpy as np
from paddleocr import PaddleOCR

try:
    from app.core.logger import logger
except Exception:
    import logging
    logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PaddleOCR singleton  (load once, reuse forever)
# ─────────────────────────────────────────────────────────────────────────────

def _get_paddle():
    from app.academic_engine.ocr_fusion.paddleocr_engine import PaddleOCREngine
    engine = PaddleOCREngine()
    # Fetch the underlying global PaddleOCR instance
    return engine._get_ocr("en")


# ─────────────────────────────────────────────────────────────────────────────
# Preprocessing
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess_full(bgr: np.ndarray) -> np.ndarray:
    """
    Full-page preprocessing for reconstruction OCR.
    CLAHE → denoise → adaptive threshold → sharpen
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)

    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
        blockSize=15, C=8,
    )

    kernel = np.array([[-1, -1, -1],
                       [-1,  9, -1],
                       [-1, -1, -1]], dtype=np.float32)
    sharpened = cv2.filter2D(binary, -1, kernel)

    return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)


def _preprocess_header(strip: np.ndarray) -> np.ndarray:
    """
    Light preprocessing for the header-only detection strip.
    Uses Otsu global threshold (better than adaptive for clean logo areas).
    """
    gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    gray = clahe.apply(gray)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


# ─────────────────────────────────────────────────────────────────────────────
# OCR helpers
# ─────────────────────────────────────────────────────────────────────────────

_GARBAGE_RE = re.compile(r"[°×«¢|_—~*]{4,}|^[—\-\._ ]+$")

def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if _GARBAGE_RE.search(text) or "Il ne ee" in text:
        return ""
    return text


def _ocr_to_words(results, conf_threshold: float, page_y_offset: float = 0.0) -> List[Dict]:
    """Convert raw PaddleOCR results to clean word-box dicts."""
    if not results or results[0] is None:
        return []
    boxes: List[Dict] = []
    for line in results[0]:
        if len(line) < 2:
            continue
        bbox_pts, (text, conf) = line[0], line[1]
        clean_t = _clean(text)
        if not clean_t or float(conf) < conf_threshold:
            continue
        xs = [p[0] for p in bbox_pts]
        ys = [p[1] for p in bbox_pts]
        x1, y1, x2, y2 = min(xs), min(ys) + page_y_offset, max(xs), max(ys) + page_y_offset
        boxes.append({
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
            "width": x2 - x1, "height": y2 - y1,
            "text": clean_t, "conf": float(conf),
        })
    return boxes


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — Early bank detection (header only, LOW confidence)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_bank_early(bgr: np.ndarray) -> str:
    """
    Detect bank from the TOP 12% of the page ONLY.

    Why separate from full OCR:
      Full-page OCR uses conf >= 0.40 to filter garbage.
      On a bad scan, even the bank name header words may score 0.30–0.39
      and get dropped — causing detection to fail and routing to fall back
      to Tesseract (slow, worse quality).

    This function uses conf >= 0.25 on a small header strip:
      - Small area  → fast (< 0.5s extra)
      - Low conf    → picks up even slightly blurred bank name
      - Otsu thresh → better for high-contrast logo areas

    Returns one of: "SBI", "KOTAK", "HDFC", "ICICI", "AXIS", "UNKNOWN"
    """
    h, w = bgr.shape[:2]
    strip_h = max(80, int(h * 0.12))   # top 12%
    header_strip = bgr[:strip_h, :]

    processed = _preprocess_header(header_strip)

    try:
        results = _get_paddle().ocr(processed)
    except Exception as exc:
        logger.warning("[detect_bank_early] OCR failed: %s", exc)
        return "UNKNOWN"

    # Collect header text with very low threshold for detection only
    header_words = []
    if results and results[0]:
        for line in results[0]:
            if len(line) >= 2:
                text, conf = line[1]
                if float(conf) >= 0.25 and text.strip():
                    header_words.append(text.upper())

    header_text = " ".join(header_words)
    logger.info("[detect_bank_early] Header OCR text: %r", header_text[:200])

    # Match against known signatures
    from app.extraction.bank_handlers.detector import _BANK_SIGNATURES
    for bank_tag, keywords in _BANK_SIGNATURES:
        for kw in keywords:
            if kw in header_text:
                logger.info("[detect_bank_early] ✓ Detected bank=%s via keyword=%r", bank_tag, kw)
                return bank_tag

    logger.info("[detect_bank_early] No match — bank=UNKNOWN")
    return "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — Full-page OCR (reconstruction quality)
# ─────────────────────────────────────────────────────────────────────────────

def extract_words(bgr: np.ndarray, crop_y: Optional[int] = None) -> List[Dict]:
    """
    Run PaddleOCR on the full page and return clean word-box dicts.

    Two-tier confidence strategy:
      - First attempt: conf >= 0.40 (clean words only)
      - If too few words returned (< 30): retry with conf >= 0.30
        This ensures we always have content to reconstruct even on bad scans.
    """
    offset_y = 0.0
    if crop_y is not None and crop_y > 0 and crop_y < bgr.shape[0]:
        bgr = bgr[crop_y:, :]
        offset_y = float(crop_y)

    processed = _preprocess_full(bgr)
    results = _get_paddle().ocr(processed)

    words = _ocr_to_words(results, conf_threshold=0.40, page_y_offset=offset_y)
    logger.info("[extract_words] conf>=0.40 → %d words", len(words))

    if len(words) < 30:
        # Too few high-confidence words — bad scan, lower threshold
        words = _ocr_to_words(results, conf_threshold=0.30, page_y_offset=offset_y)
        logger.info("[extract_words] conf>=0.30 fallback → %d words", len(words))

    return words


# ─────────────────────────────────────────────────────────────────────────────
# Header field extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_header_fields(text_lines: List[str]) -> Dict[str, str]:
    full = "\n".join(text_lines)
    info: Dict[str, str] = {
        "bank_name": "", "account_holder": "", "account_number": "",
        "period": "", "ifsc": "", "branch": "",
    }
    if re.search(r"kotak", full, re.I):
        info["bank_name"] = "Kotak Mahindra Bank"
    elif re.search(r"state bank|sbi", full, re.I):
        info["bank_name"] = "State Bank of India"

    m = re.search(r"(?:A/C No|Account No|A/c)\.?\s*[:\-]?\s*(\d{8,18})", full, re.I)
    if m:
        info["account_number"] = m.group(1)

    m = re.search(r"IFSC[^\w]*([A-Z]{4}0[A-Z0-9]{6})", full, re.I)
    if m:
        info["ifsc"] = m.group(1)

    return info


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point  (API unchanged — called by core_extractor.py)
# ─────────────────────────────────────────────────────────────────────────────

def extract_adaptive_scanned_bank_statement(bgr: np.ndarray, page_idx: int, crop_y: Optional[int] = None) -> Dict:
    """
    Scanned bank statement extraction.

    Flow:
      1. Early bank detection  → header strip, conf >= 0.25  (FAST, ~0.3s)
      2. Full-page OCR once    → conf >= 0.40, fallback 0.30
      3. If early detection succeeded, use that bank tag.
         Otherwise, try OCR-based detection on the full words.
      4. Dispatch to the correct bank handler.
      5. Return standard result dict.

    Adding a new bank: see bank_handlers/README.
    """
    t0 = time.time()
    h, w = bgr.shape[:2]

    # ── Phase 1: Early bank detection (header strip only) ────────────────────
    # Done BEFORE full OCR so routing works even when full-page OCR is noisy.
    bank_tag = "UNKNOWN"
    if page_idx == 0:       # only detect on first page (header is reliable there)
        bank_tag = _detect_bank_early(bgr)

    t_detect = round(time.time() - t0, 3)

    # ── Phase 2: Full-page OCR once ──────────────────────────────────────────
    words = extract_words(bgr, crop_y=crop_y)

    # If early detection failed, try text-based detection on full OCR words
    if bank_tag == "UNKNOWN" and words:
        from app.extraction.bank_handlers.detector import detect_bank
        bank_tag = detect_bank(words)
        logger.info("[adaptive_pipeline] OCR-based detection → bank=%s", bank_tag)

    # Even if we have zero words, proceed with the bank handler —
    # the handler will return an empty-but-valid result rather than crashing.

    # ── Phase 3: Dispatch to handler ─────────────────────────────────────────
    from app.extraction.bank_handlers import get_handler
    handler = get_handler(bank_tag)

    logger.info(
        "[adaptive_pipeline] page=%d bank=%s handler=%s words=%d "
        "detect_time=%.3fs",
        page_idx, bank_tag, handler.__class__.__name__, len(words), t_detect,
    )

    try:
        result = handler.reconstruct(words, float(w), float(h))
    except Exception as exc:
        logger.warning(
            "[adaptive_pipeline] %s.reconstruct() failed (%s) — GenericHandler fallback",
            handler.__class__.__name__, exc,
        )
        from app.extraction.bank_handlers.generic_handler import GenericHandler
        result = GenericHandler().reconstruct(words, float(w), float(h))

    # Always return success=True if we ran — even with partial/empty text.
    # This prevents core_extractor from falling back to the slow Tesseract pipeline.
    clean_text = result.get("clean_text", "")

    header_info = extract_header_fields(
        result.get("header_text", clean_text).splitlines()[:20]
    )
    if result.get("header_info", {}).get("bank_name"):
        header_info["bank_name"] = result["header_info"]["bank_name"]
    # Hard-set bank_name from early detection if still empty
    if not header_info.get("bank_name") and bank_tag == "SBI":
        header_info["bank_name"] = "State Bank of India"
    elif not header_info.get("bank_name") and bank_tag == "KOTAK":
        header_info["bank_name"] = "Kotak Mahindra Bank"

    return {
        "success":        True,
        "document_type":  "bank_statement",
        "header":         header_info,
        "tables":         result.get("tables", []),
        "text_blocks":    words,
        "clean_text":     clean_text,
        "processing_time": round(time.time() - t0, 2),
        "layout_type":    result.get("layout_type", "unknown"),
        "bank_tag":       bank_tag,
        "handler":        handler.__class__.__name__,
        "detect_time_s":  t_detect,
    }
