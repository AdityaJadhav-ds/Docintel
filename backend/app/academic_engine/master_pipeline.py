"""
master_pipeline.py — STABILIZED
=================================
STABILIZATION MODE: No new features.
Responsibilities:
  - Orchestrate 4 stages.
  - Enforce stage contracts.
  - Isolate every stage in try/except.
  - Save per-upload debug artifacts.
  - Apply final output sanitizer.
"""
import os
import time
import uuid
import json
import logging
import traceback

import cv2
import numpy as np

from app.academic_engine.advanced_vision.pipeline import AdvancedVisionPipeline
from app.academic_engine.ocr_fusion.fusion_pipeline import OCRFusionPipeline
from app.academic_engine.ocr_fusion.tesseract_engine import TesseractEngine
from app.academic_engine.semantic_engine.semantic_parser import SemanticParser
from app.academic_engine.validation_engine.healing_pipeline import HealingPipeline
from app.academic_engine.stage_contracts import (
    make_vision_output, make_ocr_output,
    make_semantic_output, make_validation_output
)

logger = logging.getLogger(__name__)

# Directory to write per-upload debug logs
_LOGS_BASE = os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")


def _json_serialize(obj):
    """Coerce numpy types for json.dumps."""
    if isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Type {type(obj)} not serializable")


class MasterPipeline:
    """
    STABILIZED Pipeline Orchestrator.

    Rules (DO NOT BREAK):
      - Vision   → ONLY improve image.
      - OCR      → ONLY read text.
      - Semantic → ONLY find candidates.
      - Validation → ONLY approve/reject.
      - No stage may crash the pipeline (all wrapped in try/except).
      - No stage may mutate another stage's output.
    """

    def __init__(self):
        self.vision_engine = AdvancedVisionPipeline()
        self.ocr_engine = OCRFusionPipeline()
        self.semantic_engine = SemanticParser()
        self.healing_engine = HealingPipeline()

    # ─────────────────────────────────────────
    # STAGE 1 — VISION
    # ─────────────────────────────────────────
    def _run_vision(self, image: np.ndarray, debug_dir: str) -> dict:
        try:
            raw = self.vision_engine.process(image)

            success = raw.get("status") == "success"
            cleaned_image = raw.get("best_image")
            zones = raw.get("zones", {})
            metrics = raw.get("classification", {})
            errors = raw.get("warnings", []) if not success else []

            # Save debug artifact
            if cleaned_image is not None:
                cv2.imwrite(os.path.join(debug_dir, "02_cleaned.jpg"), cleaned_image)

            return make_vision_output(
                success=success,
                cleaned_image=cleaned_image,
                zones=zones,
                metrics={k: float(v) if isinstance(v, (np.float32, np.float64)) else v
                         for k, v in metrics.items()},
                errors=errors,
            )
        except Exception as e:
            logger.error(f"[Vision] Unhandled exception: {e}\n{traceback.format_exc()}")
            return make_vision_output(success=False, errors=[str(e)])

    # ─────────────────────────────────────────
    # STAGE 2 — OCR
    # ─────────────────────────────────────────
    def _run_ocr(self, image: np.ndarray, zones: dict, debug_dir: str) -> dict:
        try:
            # Default to full image if no zones detected
            if not zones or not any(zones.values()):
                h, w = image.shape[:2]
                zones = {"full_page": [(0, 0, w, h)]}

            raw = self.ocr_engine.process(image, zones)
            words = raw.get("words", [])
            merged_text = raw.get("merged_text", "")
            confidence = float(raw.get("confidence_map", {}).get("overall", 0.0))

            success = len(words) > 0

            # Save debug artifact
            artifact = {"words": words, "merged_text": merged_text, "confidence": confidence}
            _write_json(os.path.join(debug_dir, "03_ocr.json"), artifact)

            return make_ocr_output(
                success=success,
                words=words,
                merged_text=merged_text,
                confidence=confidence,
                errors=[] if success else ["No words extracted from OCR"],
            )
        except Exception as e:
            logger.error(f"[OCR] Unhandled exception: {e}\n{traceback.format_exc()}")
            return make_ocr_output(success=False, errors=[str(e)])

    # ─────────────────────────────────────────
    # STAGE 3 — SEMANTIC
    # ─────────────────────────────────────────
    def _run_semantic(self, words: list, debug_dir: str) -> dict:
        try:
            raw = self.semantic_engine.parse(words)
            fields = raw.get("fields", {})
            table_data = raw.get("table_data", {})
            debug_exp = raw.get("debug_explanation", {})

            success = len(fields) > 0
            artifact = {"fields": fields, "table_data": table_data, "debug": debug_exp}
            _write_json(os.path.join(debug_dir, "04_semantic.json"), artifact)

            return make_semantic_output(
                success=success,
                candidates={},                # reserved for future ranking pass
                extracted_fields=fields,
                rejected_fields={},
                errors=[] if success else ["Semantic parser found no fields"],
            )
        except Exception as e:
            logger.error(f"[Semantic] Unhandled exception: {e}\n{traceback.format_exc()}")
            return make_semantic_output(success=False, errors=[str(e)])

    # ─────────────────────────────────────────
    # STAGE 4 — VALIDATION
    # ─────────────────────────────────────────
    def _run_validation(self, semantic_out: dict, ocr_text: str,
                        best_image: np.ndarray, debug_dir: str) -> dict:
        try:
            extracted_fields = semantic_out["extracted_fields"]

            # Build image crops for retry (field → pixel crop)
            image_crops = {}
            for field, data in extracted_fields.items():
                if isinstance(data, dict) and "source_region" in data:
                    x, y, w, h = data["source_region"]
                    ih, iw = best_image.shape[:2]
                    x, y = max(0, x), max(0, y)
                    w = min(iw - x, w)
                    h = min(ih - y, h)
                    if w > 0 and h > 0:
                        image_crops[field] = best_image[y:y+h, x:x+w]

            tess = TesseractEngine()
            def _ocr_cb(crop_img, variant_name):
                return tess.process_region(crop_img, preprocess_type=variant_name)

            raw = self.healing_engine.process(
                extracted_fields=extracted_fields,
                full_document_text=ocr_text,
                image_crops=image_crops,
                ocr_callable=_ocr_cb,
            )
            healed = raw.get("healed_fields", {})
            warnings = raw.get("warnings", [])
            debug_logs = raw.get("debug_logs", [])

            # Sanitize: separate valid vs invalid
            valid_fields, invalid_fields = self._sanitize(healed)

            artifact = {"valid_fields": valid_fields, "invalid_fields": invalid_fields,
                        "warnings": warnings, "debug_logs": debug_logs}
            _write_json(os.path.join(debug_dir, "05_validation.json"), artifact)

            return make_validation_output(
                success=True,
                valid_fields=valid_fields,
                invalid_fields=invalid_fields,
                warnings=warnings,
                errors=[],
            )
        except Exception as e:
            logger.error(f"[Validation] Unhandled exception: {e}\n{traceback.format_exc()}")
            return make_validation_output(success=False, errors=[str(e)])

    # ─────────────────────────────────────────
    # FINAL OUTPUT SANITIZER
    # ─────────────────────────────────────────
    def _sanitize(self, healed_fields: dict) -> tuple:
        """
        Second-pass contract enforcement.
        Rules (immutable):
          - percentage: 0 ≤ float ≤ 100
          - cgpa/spi:   0 ≤ float ≤ 10
          - name fields: no digits
          - marks:      0 ≤ float ≤ 10000
        Reads original_ocr_value (preserved by HealingPipeline) to log
        rejected raw text even when value was already nullified.
        Returns: (valid_fields, invalid_fields)
        """
        valid = {}
        invalid = {}
        _name_fields = {"name", "candidate_name", "student_name", "father_name", "mother_name"}

        for field, data in healed_fields.items():
            val = data.get("value")
            ok = data.get("validated", False)
            # The raw OCR string before any nullification
            raw_ocr = data.get("original_ocr_value")

            if val is not None and ok:
                try:
                    if field == "percentage":
                        ok = 0.0 <= float(val) <= 100.0
                    elif field in ("cgpa", "spi"):
                        ok = 0.0 <= float(val) <= 10.0
                    elif field in _name_fields:
                        ok = not any(c.isdigit() for c in str(val))
                    elif field in ("total_marks", "obtained_marks"):
                        ok = 0.0 <= float(val) <= 10000.0
                except (ValueError, TypeError):
                    ok = False

            if not ok or val is None:
                # Log the raw OCR garbage for traceability
                raw_to_log = raw_ocr if raw_ocr is not None else val
                if raw_to_log is not None:
                    invalid[f"{field}_ocr_raw"] = raw_to_log
                data = {**data, "value": None, "validated": False}
            valid[field] = data

        return valid, invalid

    # ─────────────────────────────────────────
    # MAIN ENTRYPOINT
    # ─────────────────────────────────────────
    def process_document(self, image: np.ndarray, upload_id: str = None) -> dict:
        start = time.time()
        upload_id = upload_id or str(uuid.uuid4())[:8]
        debug_dir = _make_debug_dir(upload_id)
        trace = {}

        # Save original
        cv2.imwrite(os.path.join(debug_dir, "01_original.jpg"), image)

        # ── Stage 1: Vision ──────────────────
        t0 = time.time()
        vision = self._run_vision(image, debug_dir)
        trace["vision"] = _stage_trace(vision["success"], t0, vision["errors"])

        if not vision["success"]:
            return self._fail_response("Vision stage failed", vision["errors"],
                                       trace, upload_id, debug_dir)

        # ── Stage 2: OCR ────────────────────
        t0 = time.time()
        ocr = self._run_ocr(vision["cleaned_image"], vision["zones"], debug_dir)
        trace["ocr"] = _stage_trace(ocr["success"], t0, ocr["errors"])

        if not ocr["success"]:
            return self._fail_response("OCR stage failed", ocr["errors"],
                                       trace, upload_id, debug_dir)

        # ── Stage 3: Semantic ────────────────
        t0 = time.time()
        semantic = self._run_semantic(ocr["words"], debug_dir)
        trace["semantic"] = _stage_trace(semantic["success"], t0, semantic["errors"])
        # Semantic failure is non-fatal — validation still runs

        # ── Stage 4: Validation ──────────────
        t0 = time.time()
        validation = self._run_validation(
            semantic, ocr["merged_text"], vision["cleaned_image"], debug_dir
        )
        trace["validation"] = _stage_trace(validation["success"], t0, validation["errors"])

        # ── Build final response ─────────────
        all_warnings = validation["warnings"] + vision["errors"]
        final = {
            "status": "success" if validation["success"] else "partial",
            "upload_id": upload_id,
            "valid_fields": validation["valid_fields"],
            "rejected_fields": validation["invalid_fields"],
            "warnings": all_warnings,
            "extracted_data": {
                "fields": validation["valid_fields"],
                "table_data": semantic.get("extracted_fields", {}).get("table_data", {}),
            },
            "telemetry": {
                "total_time_seconds": round(time.time() - start, 2),
                "stage_trace": trace,
                "warnings": all_warnings,
                "ocr_confidence": ocr["confidence"],
                "vision_metrics": vision["metrics"],
            },
            "debug_lab": {
                "vision": {"metrics": vision["metrics"]},
                "ocr": {"merged_text": ocr["merged_text"], "confidence": ocr["confidence"]},
                "semantic": semantic.get("extracted_fields", {}),
                "validation": {},
            },
        }

        # Serialize (catches numpy leaks)
        final = json.loads(json.dumps(final, default=_json_serialize))
        _write_json(os.path.join(debug_dir, "06_final.json"), final)
        logger.info(f"[Pipeline] Done upload={upload_id} in {final['telemetry']['total_time_seconds']}s")
        return final

    def _fail_response(self, message: str, errors: list, trace: dict,
                       upload_id: str, debug_dir: str) -> dict:
        out = {
            "status": "error",
            "upload_id": upload_id,
            "message": message,
            "errors": errors,
            "valid_fields": {},
            "rejected_fields": {},
            "warnings": errors,
            "extracted_data": {"fields": {}, "table_data": {}},
            "telemetry": {"stage_trace": trace, "warnings": errors},
            "debug_lab": {},
        }
        _write_json(os.path.join(debug_dir, "06_final.json"), out)
        return out


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _stage_trace(success: bool, t0: float, errors: list) -> dict:
    return {
        "success": success,
        "elapsed_s": round(time.time() - t0, 3),
        "errors": errors,
    }


def _make_debug_dir(upload_id: str) -> str:
    path = os.path.normpath(os.path.join(_LOGS_BASE, upload_id))
    os.makedirs(path, exist_ok=True)
    return path


def _write_json(path: str, data: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=_json_serialize)
    except Exception as e:
        logger.warning(f"[Debug] Could not write {path}: {e}")
