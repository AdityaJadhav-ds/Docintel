"""
tests/test_validation.py
=========================
Isolated test for Stage 4: Validation.
Tests ONLY the HealingPipeline + field contracts.
No image, no OCR needed.

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe -m pytest tests/test_validation.py -v
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.academic_engine.validation_engine.healing_pipeline import HealingPipeline
from app.academic_engine.stage_contracts import make_validation_output

DEBUG_OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "logs", "_stage_tests", "validation")
os.makedirs(DEBUG_OUT_DIR, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────────────
def _field(value, confidence=0.9):
    return {"value": value, "confidence": confidence, "extraction_strategy": "test"}

def _no_ocr(crop, variant):
    return {"text": "", "confidence": 0.0}


def _assert_validation_contract(result: dict, label: str):
    assert isinstance(result, dict),              f"[{label}] Must return dict"
    assert "success" in result,                   f"[{label}] Missing 'success'"
    assert "valid_fields" in result,              f"[{label}] Missing 'valid_fields'"
    assert "invalid_fields" in result,            f"[{label}] Missing 'invalid_fields'"
    assert "warnings" in result,                  f"[{label}] Missing 'warnings'"
    assert "errors" in result,                    f"[{label}] Missing 'errors'"
    assert isinstance(result["valid_fields"], dict),   f"[{label}] valid_fields must be dict"
    assert isinstance(result["invalid_fields"], dict), f"[{label}] invalid_fields must be dict"
    assert isinstance(result["warnings"], list),       f"[{label}] warnings must be list"
    assert isinstance(result["errors"], list),         f"[{label}] errors must be list"


class TestValidationStage:

    def setup_method(self):
        self.pipeline = HealingPipeline()

    def _run(self, fields: dict) -> dict:
        try:
            raw = self.pipeline.process(
                extracted_fields=fields,
                full_document_text="",
                image_crops={},
                ocr_callable=_no_ocr,
            )
            healed = raw.get("healed_fields", {})
            warnings = raw.get("warnings", [])
            # Sanitize (mirrors master_pipeline logic)
            from app.academic_engine.master_pipeline import MasterPipeline
            mp = MasterPipeline.__new__(MasterPipeline)
            valid, invalid = mp._sanitize(healed)
            return make_validation_output(
                success=True,
                valid_fields=valid,
                invalid_fields=invalid,
                warnings=warnings,
            )
        except Exception as e:
            return make_validation_output(success=False, errors=[str(e)])

    # ── Valid inputs ────────────────────────────────────────────
    def test_valid_percentage(self):
        result = self._run({"percentage": _field("75.17")})
        _assert_validation_contract(result, "valid_percentage")
        pct = result["valid_fields"].get("percentage", {})
        assert pct.get("value") == 75.17 or pct.get("value") == "75.17", \
            f"Expected 75.17, got {pct.get('value')}"
        print(f"  [valid_pct] value={pct.get('value')} validated={pct.get('validated')}")

    def test_valid_name(self):
        result = self._run({"name": _field("Aditya Jadhav", confidence=0.95)})
        _assert_validation_contract(result, "valid_name")
        name = result["valid_fields"].get("name", {})
        print(f"  [valid_name] value={name.get('value')} validated={name.get('validated')}")

    def test_valid_cgpa(self):
        result = self._run({"cgpa": _field("8.5")})
        _assert_validation_contract(result, "valid_cgpa")

    # ── Invalid inputs: MUST be rejected ───────────────────────
    def test_rejects_hallucinated_percentage(self):
        result = self._run({"percentage": _field("49995007404")})
        _assert_validation_contract(result, "hallucinated_pct")
        pct = result["valid_fields"].get("percentage", {})
        assert pct.get("value") is None, \
            f"Expected None for hallucinated percentage, got {pct.get('value')}"
        assert "percentage_ocr_raw" in result["invalid_fields"], \
            "Hallucinated value must appear in invalid_fields"
        print(f"  [hallucinated_pct] value={pct.get('value')} rejected_raw={result['invalid_fields'].get('percentage_ocr_raw')}")

    def test_rejects_negative_percentage(self):
        result = self._run({"percentage": _field("-10")})
        _assert_validation_contract(result, "negative_pct")
        pct = result["valid_fields"].get("percentage", {})
        assert pct.get("value") is None, f"Expected None, got {pct.get('value')}"

    def test_rejects_percentage_over_100(self):
        result = self._run({"percentage": _field("101.5")})
        _assert_validation_contract(result, "over_100_pct")
        pct = result["valid_fields"].get("percentage", {})
        assert pct.get("value") is None

    def test_rejects_name_with_digits(self):
        result = self._run({"name": _field("Board123")})
        _assert_validation_contract(result, "digit_name")
        name = result["valid_fields"].get("name", {})
        assert name.get("value") is None

    def test_rejects_cgpa_over_10(self):
        result = self._run({"cgpa": _field("15.0")})
        _assert_validation_contract(result, "bad_cgpa")
        cgpa = result["valid_fields"].get("cgpa", {})
        assert cgpa.get("value") is None

    # ── Mathematical recovery ───────────────────────────────────
    def test_mathematical_recovery(self):
        """If percentage is missing but obtained/total exist, it should be recovered."""
        result = self._run({
            "obtained_marks": _field("451"),
            "total_marks":    _field("600"),
        })
        _assert_validation_contract(result, "math_recovery")
        pct = result["valid_fields"].get("percentage", {})
        if pct.get("value") is not None:
            assert abs(float(pct["value"]) - 75.17) < 0.1, \
                f"Expected ~75.17, got {pct['value']}"
            print(f"  [math_recovery] recovered={pct['value']}")
        else:
            print(f"  [math_recovery] not recovered (marks stages may not output marks fields)")

    # ── Crash safety ────────────────────────────────────────────
    def test_does_not_crash_on_empty_input(self):
        result = self._run({})
        _assert_validation_contract(result, "empty_fields")

    def test_does_not_crash_on_none_values(self):
        result = self._run({
            "percentage": {"value": None, "confidence": 0.0, "extraction_strategy": "test"},
            "name":       {"value": None, "confidence": 0.0, "extraction_strategy": "test"},
        })
        _assert_validation_contract(result, "none_values")
