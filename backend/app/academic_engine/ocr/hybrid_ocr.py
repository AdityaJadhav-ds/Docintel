"""
academic_engine/ocr/hybrid_ocr.py
===================================
Hybrid OCR Engine with Voting System

Strategy by document type:
  Digital PDFs   → PyMuPDF first, pdfplumber fallback
  Scanned/Images → Tesseract + EasyOCR parallel, voting for best result

OCR Voting:
  - Run multiple OCR engines
  - Compare character-level confidence
  - Return highest-confidence extraction per field

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List
import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ENGINE WRAPPERS
# ─────────────────────────────────────────────────────────────────────────────

def _run_tesseract(img: np.ndarray, config: str = "--oem 3 --psm 6") -> Dict[str, Any]:
    """Run Tesseract OCR on a numpy array."""
    try:
        # import pytesseract
        import cv2
        # Ensure uint8
        if img.dtype != np.uint8:
            img = img.astype(np.uint8)
        # If binary (2D), keep as-is; else ensure BGR
        if len(img.shape) == 3 and img.shape[2] == 3:
            pass  # already BGR
        text = pytesseract.image_to_string(img, config=config, lang="eng")
        data = pytesseract.image_to_data(img, config=config, lang="eng",
                                          output_type=pytesseract.Output.DICT)
        confs = [c for c in data["conf"] if isinstance(c, (int, float)) and c > 0]
        avg_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return {
            "engine":     "tesseract",
            "text":       text.strip(),
            "confidence": round(avg_conf, 3),
            "success":    bool(text.strip()),
        }
    except Exception as exc:
        logger.warning("[hybrid_ocr] Tesseract failed: %s", exc)
        return {"engine": "tesseract", "text": "", "confidence": 0.0, "success": False}


def _run_tesseract_psm7(img: np.ndarray, whitelist: str = "") -> Dict[str, Any]:
    """Single-line OCR (PSM 7) optimised for percentage/number lines."""
    config = "--oem 3 --psm 7"
    if whitelist:
        config += f" -c tessedit_char_whitelist={whitelist}"
    return _run_tesseract(img, config=config)


def _run_easyocr(img: np.ndarray) -> Dict[str, Any]:
    """Run EasyOCR on image. Lazy-imported to avoid startup cost."""
    try:
        import easyocr
        reader = _get_easyocr_reader()
        if reader is None:
            return {"engine": "easyocr", "text": "", "confidence": 0.0, "success": False}

        if len(img.shape) == 2:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
        elif len(img.shape) == 3 and img.shape[2] == 3:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        results = reader.readtext(img, detail=1)
        texts   = []
        confs   = []
        for (bbox, text, conf) in results:
            texts.append(text)
            confs.append(conf)

        full_text = " ".join(texts)
        avg_conf  = (sum(confs) / len(confs)) if confs else 0.0

        return {
            "engine":     "easyocr",
            "text":       full_text.strip(),
            "confidence": round(avg_conf, 3),
            "success":    bool(full_text.strip()),
        }
    except Exception as exc:
        logger.warning("[hybrid_ocr] EasyOCR failed: %s", exc)
        return {"engine": "easyocr", "text": "", "confidence": 0.0, "success": False}


# EasyOCR reader singleton (expensive to initialise)
_easyocr_reader = None

def _get_easyocr_reader():
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            logger.info("[hybrid_ocr] EasyOCR reader initialised")
        except Exception as exc:
            logger.warning("[hybrid_ocr] EasyOCR unavailable: %s", exc)
            _easyocr_reader = None
    return _easyocr_reader


def _run_pymupdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """Extract text from digital PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
        doc  = fitz.open(stream=pdf_bytes, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text("text")
        doc.close()
        return {
            "engine":     "pymupdf",
            "text":       text.strip(),
            "confidence": 0.95 if text.strip() else 0.0,
            "success":    bool(text.strip()),
        }
    except Exception as exc:
        logger.warning("[hybrid_ocr] PyMuPDF failed: %s", exc)
        return {"engine": "pymupdf", "text": "", "confidence": 0.0, "success": False}


def _run_pdfplumber(pdf_bytes: bytes) -> Dict[str, Any]:
    """Extract text from digital PDF using pdfplumber."""
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        return {
            "engine":     "pdfplumber",
            "text":       text.strip(),
            "confidence": 0.93 if text.strip() else 0.0,
            "success":    bool(text.strip()),
        }
    except Exception as exc:
        logger.warning("[hybrid_ocr] pdfplumber failed: %s", exc)
        return {"engine": "pdfplumber", "text": "", "confidence": 0.0, "success": False}


# ─────────────────────────────────────────────────────────────────────────────
# VOTING SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

def _vote_best(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Given multiple OCR results, return the one with:
      1. success=True
      2. highest confidence
      3. longest text (tie-break)
    """
    valid = [r for r in results if r.get("success") and r.get("text")]
    if not valid:
        # Return best-effort even if confidence is 0
        return max(results, key=lambda r: (r.get("confidence", 0), len(r.get("text", ""))))
    return max(valid, key=lambda r: (r.get("confidence", 0), len(r.get("text", ""))))


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def ocr_image(
    img: np.ndarray,
    use_easyocr: bool = True,
    config: str = "--oem 3 --psm 6",
) -> Dict[str, Any]:
    """
    Full-page image OCR with voting.

    Args:
        img:         Preprocessed image array.
        use_easyocr: If True, also run EasyOCR and vote.
        config:      Tesseract config string.

    Returns:
        {text, confidence, engine, engines_tried, all_results}
    """
    results = []

    # Always run Tesseract
    tess = _run_tesseract(img, config=config)
    results.append(tess)
    logger.debug("[hybrid_ocr] Tesseract conf=%.2f len=%d", tess["confidence"], len(tess["text"]))

    # Optionally run EasyOCR
    if use_easyocr:
        easy = _run_easyocr(img)
        results.append(easy)
        logger.debug("[hybrid_ocr] EasyOCR conf=%.2f len=%d", easy["confidence"], len(easy["text"]))

    best = _vote_best(results)
    engines_tried = [r["engine"] for r in results]

    logger.info("[hybrid_ocr] Winner: %s conf=%.2f len=%d",
                best["engine"], best["confidence"], len(best["text"]))

    return {
        "text":         best["text"],
        "confidence":   best["confidence"],
        "engine":       best["engine"],
        "engines_tried":engines_tried,
        "all_results":  results,
    }


def ocr_roi_percentage(img: np.ndarray) -> Dict[str, Any]:
    """
    Dedicated percentage ROI OCR.
    Config: PSM 7, whitelist digits + period + percent.
    """
    whitelist = "0123456789.%"
    return _run_tesseract_psm7(img, whitelist=whitelist)


def ocr_roi_line(img: np.ndarray) -> Dict[str, Any]:
    """Single-line OCR (PSM 7) for short text fields like name/year."""
    return _run_tesseract(img, config="--oem 3 --psm 7")


def ocr_roi_block(img: np.ndarray) -> Dict[str, Any]:
    """Block OCR (PSM 6) for multi-line zones like header/cert statement."""
    tess = _run_tesseract(img, config="--oem 3 --psm 6")
    easy = _run_easyocr(img)
    best = _vote_best([tess, easy])
    return {
        "text":         best["text"],
        "confidence":   best["confidence"],
        "engine":       best["engine"],
        "engines_tried":["tesseract", "easyocr"],
    }


def ocr_pdf(pdf_bytes: bytes) -> Dict[str, Any]:
    """
    PDF-aware OCR:
      1. Try PyMuPDF (digital text extraction)
      2. Fallback to pdfplumber
      3. If both fail, signal caller to rasterise and use image OCR
    """
    mudf = _run_pymupdf(pdf_bytes)
    if mudf["success"] and len(mudf["text"]) > 100:
        logger.info("[hybrid_ocr] PyMuPDF extraction succeeded (%d chars)", len(mudf["text"]))
        return mudf

    plmb = _run_pdfplumber(pdf_bytes)
    if plmb["success"] and len(plmb["text"]) > 100:
        logger.info("[hybrid_ocr] pdfplumber extraction succeeded (%d chars)", len(plmb["text"]))
        return plmb

    logger.info("[hybrid_ocr] PDF text extraction yielded little text — caller should rasterise")
    return {
        "text":         mudf.get("text") or plmb.get("text") or "",
        "confidence":   0.0,
        "engine":       "pdf_text_failed",
        "engines_tried":["pymupdf", "pdfplumber"],
        "needs_rasterise": True,
    }
