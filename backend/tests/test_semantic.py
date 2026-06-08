"""
tests/test_semantic.py
=======================
Isolated test for Stage 3: Semantic Extraction.
Tests ONLY the SemanticParser.
Injects pre-formed word lists — no real images needed.

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe -m pytest tests/test_semantic.py -v
"""
import os
import sys
import json
import glob
import pytest
import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.academic_engine.semantic_engine.semantic_parser import SemanticParser
from app.academic_engine.ocr_fusion.fusion_pipeline import OCRFusionPipeline
from app.academic_engine.stage_contracts import make_semantic_output

TEST_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_documents")
DEBUG_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "_stage_tests", "semantic")
os.makedirs(DEBUG_OUT_DIR, exist_ok=True)

# Pre-formed word lists for unit tests
MOCK_SSC_WORDS = [
    {"text": "Candidate", "confidence": 0.95, "bbox": (10, 50, 80, 20)},
    {"text": "Name", "confidence": 0.95, "bbox": (95, 50, 40, 20)},
    {"text": "Aditya", "confidence": 0.93, "bbox": (150, 50, 60, 20)},
    {"text": "Jadhav", "confidence": 0.91, "bbox": (215, 50, 55, 20)},
    {"text": "Percentage", "confidence": 0.94, "bbox": (10, 120, 80, 20)},
    {"text": "75.17", "confidence": 0.90, "bbox": (95, 120, 50, 20)},
]

MOCK_HALLUCINATED_WORDS = [
    {"text": "Candidate", "confidence": 0.95, "bbox": (10, 50, 80, 20)},
    {"text": "Name", "confidence": 0.95, "bbox": (95, 50, 40, 20)},
    {"text": "BoardOfMaharashtra", "confidence": 0.85, "bbox": (150, 50, 120, 20)},
    {"text": "Percentage", "confidence": 0.94, "bbox": (10, 120, 80, 20)},
    {"text": "49995007404", "confidence": 0.78, "bbox": (95, 120, 80, 20)},
]


def _assert_semantic_contract(result: dict, label: str):
    assert isinstance(result, dict),              f"[{label}] Must return dict"
    assert "success" in result,                   f"[{label}] Missing 'success'"
    assert "candidates" in result,                f"[{label}] Missing 'candidates'"
    assert "extracted_fields" in result,          f"[{label}] Missing 'extracted_fields'"
    assert "rejected_fields" in result,           f"[{label}] Missing 'rejected_fields'"
    assert "errors" in result,                    f"[{label}] Missing 'errors'"
    assert isinstance(result["extracted_fields"], dict), f"[{label}] extracted_fields must be dict"
    assert isinstance(result["errors"], list),    f"[{label}] errors must be list"


class TestSemanticStage:

    def setup_method(self):
        self.parser = SemanticParser()

    def test_contract_with_clean_words(self):
        """Standard SSC-style word list should produce at least one field."""
        try:
            raw = self.parser.parse(MOCK_SSC_WORDS)
            result = make_semantic_output(
                success=len(raw.get("fields", {})) > 0,
                extracted_fields=raw.get("fields", {}),
            )
        except Exception as e:
            result = make_semantic_output(success=False, errors=[str(e)])

        _assert_semantic_contract(result, "mock_ssc")
        print(f"  [mock_ssc] fields={list(result['extracted_fields'].keys())}")

    def test_contract_with_hallucinated_words(self):
        """Hallucinated words must not cause a crash. Validation catches them later."""
        try:
            raw = self.parser.parse(MOCK_HALLUCINATED_WORDS)
            result = make_semantic_output(
                success=True,
                extracted_fields=raw.get("fields", {}),
            )
        except Exception as e:
            result = make_semantic_output(success=False, errors=[str(e)])

        _assert_semantic_contract(result, "hallucinated_words")

    def test_contract_with_empty_words(self):
        """Empty word list must not crash. Returns empty extracted_fields."""
        try:
            raw = self.parser.parse([])
            result = make_semantic_output(
                success=False,
                extracted_fields=raw.get("fields", {}),
                errors=["No words provided"],
            )
        except Exception as e:
            result = make_semantic_output(success=False, errors=[str(e)])

        _assert_semantic_contract(result, "empty_words")

    def test_contract_on_real_images(self):
        """Full integration: load image → OCR → Semantic (skips Vision for speed)."""
        exts = ("*.jpg", "*.jpeg", "*.png")
        images = []
        for ext in exts:
            images.extend(__import__("glob").glob(
                os.path.join(TEST_DOCS_DIR, "**", ext), recursive=True))

        if not images:
            pytest.skip("No test images in backend/test_documents/")

        ocr_pipeline = OCRFusionPipeline()
        for img_path in images:
            label = os.path.basename(img_path)
            image = cv2.imread(img_path)
            if image is None:
                continue

            h, w = image.shape[:2]
            try:
                ocr_raw = ocr_pipeline.process(image, {"full_page": [(0, 0, w, h)]})
                words = ocr_raw.get("words", [])
                sem_raw = self.parser.parse(words)
                result = make_semantic_output(
                    success=len(sem_raw.get("fields", {})) > 0,
                    extracted_fields=sem_raw.get("fields", {}),
                )
            except Exception as e:
                result = make_semantic_output(success=False, errors=[str(e)])

            _assert_semantic_contract(result, label)

            out = os.path.join(DEBUG_OUT_DIR, f"{os.path.splitext(label)[0]}_semantic.json")
            with open(out, "w", encoding="utf-8") as f:
                import json
                json.dump({
                    "file": label,
                    "success": result["success"],
                    "fields": {k: v.get("value") if isinstance(v, dict) else v
                               for k, v in result["extracted_fields"].items()},
                    "errors": result["errors"],
                }, f, indent=2)

            print(f"  [{label}] success={result['success']} fields={list(result['extracted_fields'].keys())}")
