"""
app/ocr/region_ocr.py
=======================
Stub shim — ocr_router removed in universal pipeline rebuild.
KYC parser region OCR is not part of the main extraction path.
"""
from __future__ import annotations
from typing import Dict
import numpy as np


def _preprocess_region(crop: np.ndarray) -> np.ndarray:
    try:
        import cv2
        if len(crop.shape) == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop.copy()
        return gray
    except Exception:
        return crop


def ocr_pan_regions(image: np.ndarray) -> Dict:
    """Run OCR on a PAN card image region using PaddleOCR."""
    try:
        import cv2
        from app.extraction.pipeline import _get_ocr
        from app.extraction.geometry import flatten_paddle_result

        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image

        ocr = _get_ocr()
        raw = ocr.ocr(gray, cls=False)
        flat = raw[0] if raw and isinstance(raw[0], list) else (raw or [])
        boxes = flatten_paddle_result(flat)
        text = " ".join(b["text"] for b in boxes)
        avg_conf = sum(b["confidence"] for b in boxes) / max(len(boxes), 1)
        return {"text": text, "confidence": avg_conf}
    except Exception:
        return {"text": "", "confidence": 0.0}
