"""
tests/test_vision.py
=====================
Isolated test for Stage 1: Vision.
Tests ONLY the AdvancedVisionPipeline.
No OCR, no semantic, no validation.

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe -m pytest tests/test_vision.py -v
"""
import os
import sys
import json
import glob
import pytest
import cv2
import numpy as np

# Make sure backend root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.academic_engine.advanced_vision.pipeline import AdvancedVisionPipeline

# ── Image discovery ───────────────────────────────────────────────────
TEST_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_documents")
DEBUG_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "_stage_tests", "vision")
os.makedirs(DEBUG_OUT_DIR, exist_ok=True)

def _get_test_images():
    exts = ("*.jpg", "*.jpeg", "*.png")
    images = []
    for ext in exts:
        images.extend(glob.glob(os.path.join(TEST_DOCS_DIR, "**", ext), recursive=True))
    return images if images else []


# ── Contract validator ────────────────────────────────────────────────
def _assert_vision_contract(result: dict, label: str):
    assert isinstance(result, dict), f"[{label}] Must return a dict"
    assert "success" in result,       f"[{label}] Missing 'success' key"
    assert "cleaned_image" in result, f"[{label}] Missing 'cleaned_image'"
    assert "zones" in result,         f"[{label}] Missing 'zones'"
    assert "metrics" in result,       f"[{label}] Missing 'metrics'"
    assert "errors" in result,        f"[{label}] Missing 'errors'"
    assert isinstance(result["zones"], dict),  f"[{label}] zones must be dict"
    assert isinstance(result["errors"], list), f"[{label}] errors must be list"


# ── Tests ─────────────────────────────────────────────────────────────
class TestVisionStage:

    def setup_method(self):
        self.pipeline = AdvancedVisionPipeline()

    def test_contract_on_real_images(self):
        """Contract check on every image in test_documents/."""
        images = _get_test_images()
        if not images:
            pytest.skip("No test images found in backend/test_documents/")

        for img_path in images:
            label = os.path.basename(img_path)
            image = cv2.imread(img_path)
            assert image is not None, f"Could not load {img_path}"

            raw = self.pipeline.process(image)

            # Wrap in contract (mirrors master_pipeline._run_vision)
            from app.academic_engine.stage_contracts import make_vision_output
            result = make_vision_output(
                success=raw.get("status") == "success",
                cleaned_image=raw.get("best_image"),
                zones=raw.get("zones", {}),
                metrics={k: float(v) if isinstance(v, (float, int)) else v
                         for k, v in raw.get("classification", {}).items()},
                errors=raw.get("warnings", []),
            )
            _assert_vision_contract(result, label)

            # Save debug output image
            if result["cleaned_image"] is not None:
                out_name = f"{os.path.splitext(label)[0]}_cleaned.jpg"
                cv2.imwrite(os.path.join(DEBUG_OUT_DIR, out_name), result["cleaned_image"])

            # Save metrics JSON
            meta = {
                "file": label,
                "success": result["success"],
                "zones_detected": {k: len(v) for k, v in result["zones"].items()},
                "metrics": result["metrics"],
                "errors": result["errors"],
            }
            with open(os.path.join(DEBUG_OUT_DIR, f"{os.path.splitext(label)[0]}_meta.json"), "w") as f:
                json.dump(meta, f, indent=2)

            print(f"  [{label}] success={result['success']} zones={list(result['zones'].keys())}")

    def test_contract_on_blank_image(self):
        """Vision must not crash on a blank white image."""
        blank = np.ones((800, 600, 3), dtype=np.uint8) * 255
        raw = self.pipeline.process(blank)
        from app.academic_engine.stage_contracts import make_vision_output
        result = make_vision_output(
            success=raw.get("status") == "success",
            cleaned_image=raw.get("best_image"),
            zones=raw.get("zones", {}),
            metrics={},
            errors=raw.get("warnings", []),
        )
        _assert_vision_contract(result, "blank_image")
        # Even if it fails, it must return the correct structure
        assert result["errors"] is not None
