"""
app/ocr/engine.py
==================
Stub shim — ocr_router removed in universal pipeline rebuild.
Functions in this module are no longer part of the main extraction path.
They are kept here for backward compatibility with any remaining code
that imports from app.ocr.engine, but they return empty results.
"""
from __future__ import annotations
from typing import Dict
import numpy as np


def run_ocr_on_variants(variants: Dict[str, np.ndarray]) -> Dict:
    """
    OCR via PaddleOCR on the first available image variant.
    Replaces the old ocr_router shim.
    """
    try:
        import cv2
        from app.extraction.pipeline import _get_ocr
        from app.extraction.geometry import flatten_paddle_result

        best_arr = None
        for key in ("original", "gray", "clahe"):
            if key in variants:
                best_arr = variants[key]
                break
        if best_arr is None and variants:
            best_arr = next(iter(variants.values()))
        if best_arr is None:
            return {"merged_text": "", "line_boxes": [], "engines_used": [], "avg_confidence": 0.0}

        if len(best_arr.shape) == 2:
            img = best_arr
        else:
            img = cv2.cvtColor(best_arr, cv2.COLOR_BGR2GRAY)

        ocr = _get_ocr()
        raw = ocr.ocr(img, cls=False)
        flat = raw[0] if raw and isinstance(raw[0], list) else (raw or [])
        boxes = flatten_paddle_result(flat)
        text = " ".join(b["text"] for b in boxes)
        avg_conf = sum(b["confidence"] for b in boxes) / max(len(boxes), 1)

        line_boxes = [{
            "text": b["text"],
            "confidence": b["confidence"],
            "bbox": b["bbox"],
        } for b in boxes]

        return {
            "merged_text": text,
            "variant_texts": {"primary": text},
            "line_boxes": line_boxes,
            "engines_used": ["paddleocr"],
            "avg_confidence": avg_conf,
            "detected_script": "Latin",
            "ocr_lang": "en",
        }
    except Exception as exc:
        return {
            "merged_text": "", "variant_texts": {}, "line_boxes": [],
            "engines_used": [], "avg_confidence": 0.0,
            "detected_script": "Latin", "ocr_lang": "en",
        }
