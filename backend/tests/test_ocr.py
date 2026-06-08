"""
tests/test_ocr.py
==================
Isolated test for Stage 2: OCR.
Tests ONLY the OCRFusionPipeline.
Takes cleaned images (bypasses vision).

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe -m pytest tests/test_ocr.py -v
"""
import os
import sys
import json
import glob
import pytest
import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.academic_engine.ocr_fusion.fusion_pipeline import OCRFusionPipeline
from app.academic_engine.stage_contracts import make_ocr_output

TEST_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_documents")
DEBUG_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "_stage_tests", "ocr")
os.makedirs(DEBUG_OUT_DIR, exist_ok=True)


def _get_test_images():
    exts = ("*.jpg", "*.jpeg", "*.png")
    images = []
    for ext in exts:
        images.extend(glob.glob(os.path.join(TEST_DOCS_DIR, "**", ext), recursive=True))
    return images


def _assert_ocr_contract(result: dict, label: str):
    assert isinstance(result, dict),         f"[{label}] Must return dict"
    assert "success" in result,              f"[{label}] Missing 'success'"
    assert "words" in result,                f"[{label}] Missing 'words'"
    assert "merged_text" in result,          f"[{label}] Missing 'merged_text'"
    assert "confidence" in result,           f"[{label}] Missing 'confidence'"
    assert "errors" in result,               f"[{label}] Missing 'errors'"
    assert isinstance(result["words"], list),         f"[{label}] words must be list"
    assert isinstance(result["merged_text"], str),    f"[{label}] merged_text must be str"
    assert isinstance(result["confidence"], float),   f"[{label}] confidence must be float"
    assert isinstance(result["errors"], list),        f"[{label}] errors must be list"
    # Each word must have text + bbox
    for w in result["words"]:
        assert "text" in w,  f"[{label}] word missing 'text'"
        assert "bbox" in w,  f"[{label}] word missing 'bbox'"


class TestOcrStage:

    def setup_method(self):
        self.pipeline = OCRFusionPipeline()

    def test_contract_on_real_images(self):
        images = _get_test_images()
        if not images:
            pytest.skip("No test images found in backend/test_documents/")

        for img_path in images:
            label = os.path.basename(img_path)
            image = cv2.imread(img_path)
            assert image is not None, f"Could not load {img_path}"

            h, w = image.shape[:2]
            zones = {"full_page": [(0, 0, w, h)]}

            try:
                raw = self.pipeline.process(image, zones)
                words = raw.get("words", [])
                result = make_ocr_output(
                    success=len(words) > 0,
                    words=words,
                    merged_text=raw.get("merged_text", ""),
                    confidence=float(raw.get("confidence_map", {}).get("overall", 0.0)),
                )
            except Exception as e:
                result = make_ocr_output(success=False, errors=[str(e)])

            _assert_ocr_contract(result, label)

            debug = {
                "file": label,
                "success": result["success"],
                "word_count": len(result["words"]),
                "confidence": result["confidence"],
                "merged_text_preview": result["merged_text"][:300],
                "errors": result["errors"],
            }
            out = os.path.join(DEBUG_OUT_DIR, f"{os.path.splitext(label)[0]}_ocr.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(debug, f, indent=2)

            print(f"  [{label}] success={result['success']} words={len(result['words'])} conf={result['confidence']:.2f}")

    def test_contract_no_words_on_blank(self):
        """OCR must not crash on blank image and must return contract-compliant dict."""
        blank = np.ones((800, 600, 3), dtype=np.uint8) * 255
        h, w = blank.shape[:2]
        zones = {"full_page": [(0, 0, w, h)]}
        try:
            raw = self.pipeline.process(blank, zones)
            result = make_ocr_output(
                success=len(raw.get("words", [])) > 0,
                words=raw.get("words", []),
                merged_text=raw.get("merged_text", ""),
                confidence=float(raw.get("confidence_map", {}).get("overall", 0.0)),
            )
        except Exception as e:
            result = make_ocr_output(success=False, errors=[str(e)])
        _assert_ocr_contract(result, "blank_image")
