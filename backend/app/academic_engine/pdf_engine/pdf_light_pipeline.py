"""
pdf_engine/pdf_light_pipeline.py
=================================
FAST MODE for PDFs.

PDFs are already clean digital images at 400 DPI.
They do NOT need mobile-image recovery logic.

This pipeline bypasses:
  - Heavy vision preprocessing (glare/shadow/super-resolution/heatmaps)
  - Multi-engine OCR fusion (Tesseract + EasyOCR + PaddleOCR)
  - Retry loops and localized re-OCR
  - All 5 preprocessing variants per region

Uses ONLY:
  - PaddleOCR (fastest, best for clean printed text)
  - 2 variants: grayscale + sharpened
  - Light normalization (brightness + contrast only)
  - Standard semantic + validation pass

Target: 5–15 seconds per PDF page.
"""
from __future__ import annotations

import gc
import logging
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import List, Dict, Any

import cv2
import numpy as np

logger = logging.getLogger("docvalidator")

# ── Stage timeout limits (seconds) ───────────────────────────────────
# OCR is the heaviest stage — 20s is generous for 250 DPI images
_OCR_TIMEOUT_S       = 20
_SEMANTIC_TIMEOUT_S  = 10
_VALIDATE_TIMEOUT_S  = 8


# ─── Light Vision: bypass heavy preprocessing ─────────────────────────────────

def _light_preprocess(image: np.ndarray) -> np.ndarray:
    """
    Minimal preprocessing for clean PDF images.
    SKIP: glare removal, shadow removal, super-resolution, contour detection.
    KEEP: brightness normalisation + mild sharpening.
    """
    # Convert to BGR if needed
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    # Mild CLAHE brightness normalisation
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
    l = clahe.apply(l)
    image = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)

    # Very light sharpening
    blurred = cv2.GaussianBlur(image, (0, 0), sigmaX=0.8)
    image = cv2.addWeighted(image, 1.3, blurred, -0.3, 0)

    return image


def _light_zones(image: np.ndarray) -> dict:
    """Return a single full-page zone — PDFs don't need zone decomposition."""
    h, w = image.shape[:2]
    return {"full_page": [(0, 0, w, h)]}


# ─── Light OCR: PaddleOCR only, 2 variants ────────────────────────────────────

def _run_paddle_only(image: np.ndarray) -> dict:
    """
    Run PaddleOCR on grayscale + sharpened variants.
    Falls back to Tesseract if PaddleOCR returns nothing.
    Returns OCR output in the same format as OCRFusionPipeline.process().
    """
    from app.academic_engine.ocr_fusion.paddleocr_engine import PaddleOCREngine
    paddle = PaddleOCREngine()

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    kernel = np.array([[-1, -1, -1], [-1, 9, -1], [-1, -1, -1]])
    sharp = cv2.filter2D(gray, -1, kernel)

    all_words: List[dict] = []
    seen: set = set()

    def _dedup_add(results, variant):
        for r in (results or []):
            key = (r.get("text", ""), r.get("bbox", (0,))[0])
            if key not in seen:
                seen.add(key)
                all_words.append({
                    "text":       r.get("text", ""),
                    "confidence": float(r.get("confidence", 0.5)),
                    "bbox":       r.get("bbox", (0, 0, 0, 0)),
                })

    # ── PaddleOCR: grayscale only (optimized pass) ────────────────────────────────
    for variant_name, variant_img in [("grayscale", gray)]:
        try:
            # NOTE: engine signature uses 'preprocess_type', NOT 'variant_name'
            results = paddle.process_region(variant_img, lang="en", preprocess_type=variant_name)
            _dedup_add(results, variant_name)
        except Exception as exc:
            logger.warning("[pdf_light] PaddleOCR variant %s failed: %s", variant_name, exc)

    # ── Tesseract fallback: if PaddleOCR yielded nothing ────────────────
    if not all_words:
        logger.info("[pdf_light] PaddleOCR returned 0 words — running Tesseract fallback")
        try:
            from app.academic_engine.ocr_fusion.tesseract_engine import TesseractEngine
            tess = TesseractEngine()
            results = tess.process_region(gray, lang="eng", preprocess_type="grayscale")
            _dedup_add(results, "tesseract_gray")
        except Exception as exc:
            logger.warning("[pdf_light] Tesseract fallback failed: %s", exc)

    # Sort top-to-bottom, left-to-right
    all_words.sort(key=lambda w: (w["bbox"][1] // 15, w["bbox"][0]))
    merged_text = " ".join(w["text"] for w in all_words)

    overall_conf = (
        sum(w["confidence"] for w in all_words) / len(all_words)
        if all_words else 0.0
    )

    logger.info("[pdf_light] OCR complete: %d words, conf=%.3f", len(all_words), overall_conf)

    return {
        "words":          all_words,
        "merged_text":    merged_text,
        "confidence_map": {"overall": overall_conf},
        "success":        len(all_words) > 0,
        "errors":         [] if all_words else ["All OCR engines returned no words"],
    }



# ─── Light Healing: no retry loops ────────────────────────────────────────────

def _run_light_healing(extracted_fields: dict, full_text: str) -> dict:
    """
    Stripped-down validation — no localized re-OCR retries.
    Runs: hallucination check → field validation → confidence recalibration.
    """
    try:
        from app.academic_engine.validation_engine.hallucination_detector import HallucinationDetector
        from app.academic_engine.validation_engine.field_validator import FieldValidator
        from app.academic_engine.validation_engine.numeric_repair import NumericRepair
        hal_det  = HallucinationDetector()
        validator = FieldValidator()
        repair    = NumericRepair()
    except Exception as exc:
        logger.warning("[pdf_light] Validation imports failed: %s", exc)
        return {"healed_fields": extracted_fields, "warnings": [], "debug_logs": []}

    healed = {}
    warnings = []

    for field_name, field_data in extracted_fields.items():
        value = field_data.get("value")
        conf  = field_data.get("confidence", 0.0)
        is_valid = True

        # 1. Hallucination check
        try:
            is_hal, msg = hal_det.is_hallucination(field_name, value, conf)
            if is_hal:
                is_valid = False
                warnings.append(f"[PDF] Hallucination in {field_name}: {msg}")
                value = None
        except Exception:
            pass

        # 2. Numeric repair
        if is_valid and field_name in ("percentage", "cgpa", "spi", "total_marks", "obtained_marks"):
            try:
                value, _ = repair.repair(value, field_name)
            except Exception:
                pass

        # 3. Field validation (no retry)
        if is_valid and value is not None:
            try:
                if field_name == "name":
                    is_valid, _ = validator.validate_name(value, conf)
                elif field_name == "percentage":
                    is_valid, _ = validator.validate_percentage(value)
                elif field_name in ("cgpa", "spi"):
                    is_valid, _ = validator.validate_cgpa(value)
                elif field_name == "result":
                    is_valid, _ = validator.validate_result(value)
            except Exception:
                pass

        if not is_valid:
            value = None

        healed[field_name] = {
            "value":               value,
            "original_ocr_value":  field_data.get("value"),
            "confidence":          conf,
            "validated":           is_valid and value is not None,
            "repaired":            False,
            "retries_used":        0,
            "extraction_strategy": field_data.get("extraction_strategy", "pdf_light"),
        }

    return {"healed_fields": healed, "warnings": warnings, "debug_logs": []}


def _run_timed(fn, timeout_s: int, stage_name: str):
    """
    Run fn() in a thread with a hard timeout.
    Returns (result, timed_out, error_str).
    """
    with ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn)
        try:
            return future.result(timeout=timeout_s), False, None
        except FuturesTimeoutError:
            logger.error("[pdf_light] Stage '%s' timed out after %ds", stage_name, timeout_s)
            return None, True, f"{stage_name} timed out after {timeout_s}s"
        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("[pdf_light] Stage '%s' error: %s\n%s", stage_name, exc, tb)
            return None, False, str(exc)


# ─── Main light pipeline ───────────────────────────────────────────────────────

def run_light_pipeline(image: np.ndarray, upload_id: str,
                        native_text: str = "") -> dict:
    """
    Full light pipeline for a single PDF page image.

    Stages:
        1. Light preprocess   (no glare/shadow/super-res)
        2. PaddleOCR only    (2 variants)
        3. Semantic parser   (reuse existing, untouched)
        4. Light validation  (no retry loops)

    Returns: same dict shape as MasterPipeline.process_document()
    """
    import json
    from app.academic_engine.stage_contracts import (
        make_vision_output, make_ocr_output,
        make_semantic_output, make_validation_output,
    )

    t_start = time.time()
    trace: Dict[str, Any] = {}

    # ── Stage 1: Light preprocess ──────────────────────────────────────────
    t0 = time.time()
    try:
        clean_image = _light_preprocess(image)
        zones       = _light_zones(clean_image)
        vision = make_vision_output(
            success=True,
            cleaned_image=clean_image,
            zones=zones,
            metrics={"mode": "pdf_light"},
            errors=[],
        )
        trace["vision"] = {"success": True, "elapsed_s": round(time.time() - t0, 3), "errors": []}
    except Exception as exc:
        logger.error("[pdf_light] Vision stage failed: %s", exc)
        vision = make_vision_output(success=False, errors=[str(exc)])
        trace["vision"] = {"success": False, "elapsed_s": round(time.time() - t0, 3), "errors": [str(exc)]}
        return _fail(upload_id, "PDF light vision failed", [str(exc)], trace)

    # ── Stage 2: PaddleOCR only (with timeout) ───────────────────────
    t0 = time.time()
    ocr_raw, timed_out, err = _run_timed(
        lambda: _run_paddle_only(clean_image),
        _OCR_TIMEOUT_S, "OCR"
    )
    if timed_out or ocr_raw is None:
        return _fail(upload_id, err or "OCR failed", [err or "OCR failed"], trace)

    words       = ocr_raw.get("words", [])
    merged_text = ocr_raw.get("merged_text", "")
    ocr_conf    = float(ocr_raw.get("confidence_map", {}).get("overall", 0.0))
    ocr_success = len(words) > 0

    ocr = make_ocr_output(
        success=ocr_success,
        words=words,
        merged_text=merged_text,
        confidence=ocr_conf,
        errors=[] if ocr_success else ["PaddleOCR returned no words"],
    )
    trace["ocr"] = {"success": ocr_success, "elapsed_s": round(time.time() - t0, 3), "errors": ocr.get("errors", [])}

    # ── Supplement OCR text with native PDF text ──────────────────────────
    # Digital PDFs have embedded text that is complete and accurate.
    # PaddleOCR can miss table headers (e.g. "SPI: 8.95") in complex layouts.
    # Appending native_text ensures the semantic parser sees ALL content.
    if native_text and native_text.strip():
        merged_text = merged_text + " " + native_text.strip()
        logger.info("[pdf_light] Supplemented OCR with native text (%d chars)", len(native_text))

    del clean_image
    gc.collect()

    # ── Stage 3: Semantic parser (with timeout) ─────────────────────
    t0 = time.time()
    semantic_fields = {}
    try:
        from app.academic_engine.semantic_engine.semantic_parser import SemanticParser
        parser = SemanticParser()
        sem_raw, timed_out, sem_err = _run_timed(
            lambda: parser.parse(words, extra_text=merged_text),
            _SEMANTIC_TIMEOUT_S, "Semantic"
        )
        if sem_raw:
            semantic_fields = sem_raw.get("fields", {})
        trace["semantic"] = {"success": len(semantic_fields) > 0, "elapsed_s": round(time.time() - t0, 3),
                             "errors": [sem_err] if sem_err else []}
    except Exception as exc:
        logger.warning("[pdf_light] Semantic stage failed: %s", exc)
        trace["semantic"] = {"success": False, "elapsed_s": round(time.time() - t0, 3), "errors": [str(exc)]}

    semantic = make_semantic_output(
        success=len(semantic_fields) > 0,
        candidates={},
        extracted_fields=semantic_fields,
        rejected_fields={},
        errors=[] if semantic_fields else ["No fields found"],
    )

    # ── Stage 4: Light validation (with timeout, no retries) ───────────
    t0 = time.time()
    try:
        heal_raw, timed_out, heal_err = _run_timed(
            lambda: _run_light_healing(semantic_fields, merged_text),
            _VALIDATE_TIMEOUT_S, "Validation"
        )
        heal_out  = heal_raw or {"healed_fields": semantic_fields, "warnings": [], "debug_logs": []}
        healed    = heal_out.get("healed_fields", {})
        warnings  = heal_out.get("warnings", [])
        if heal_err:
            warnings.append(f"Validation stage warning: {heal_err}")

        # Sanitize (same rules as MasterPipeline._sanitize)
        valid_fields  = {}
        invalid_fields = {}
        _name_fields  = {"name", "candidate_name", "student_name"}
        for field, data in healed.items():
            val = data.get("value")
            ok  = data.get("validated", False)
            if val is not None and ok:
                try:
                    if field == "percentage":
                        ok = 0.0 <= float(val) <= 100.0
                    elif field in ("cgpa", "spi"):
                        ok = 0.0 <= float(val) <= 10.0
                    elif field in _name_fields:
                        ok = not any(c.isdigit() for c in str(val))
                except (ValueError, TypeError):
                    ok = False
            if not ok or val is None:
                raw = data.get("original_ocr_value")
                if raw is not None:
                    invalid_fields[f"{field}_ocr_raw"] = raw
                data = {**data, "value": None, "validated": False}
            valid_fields[field] = data

        validation = make_validation_output(
            success=True,
            valid_fields=valid_fields,
            invalid_fields=invalid_fields,
            warnings=warnings,
            errors=[],
        )
        trace["validation"] = {"success": True, "elapsed_s": round(time.time() - t0, 3), "errors": []}
    except Exception as exc:
        logger.error("[pdf_light] Validation stage failed: %s", exc)
        validation = make_validation_output(success=False, errors=[str(exc)])
        valid_fields   = {}
        invalid_fields = {}
        warnings       = []
        trace["validation"] = {"success": False, "elapsed_s": round(time.time() - t0, 3), "errors": [str(exc)]}

    gc.collect()

    elapsed = round(time.time() - t_start, 2)
    logger.info("[pdf_light] Done upload_id=%s elapsed=%.2fs words=%d fields=%d",
                upload_id, elapsed, len(words), len(valid_fields))

    has_real_values = any(
        d.get("value") is not None
        for d in valid_fields.values()
        if isinstance(d, dict)
    )

    result = {
        "status":          "success" if has_real_values else "partial",

        "upload_id":       upload_id,
        "valid_fields":    valid_fields,
        "rejected_fields": invalid_fields,
        "warnings":        warnings,
        "extracted_data": {
            "fields":     valid_fields,
            "table_data": {},
        },
        "telemetry": {
            "total_time_seconds": elapsed,
            "stage_trace":        trace,
            "warnings":           warnings,
            "ocr_confidence":     ocr_conf,
            "vision_metrics":     {"mode": "pdf_light"},
            "pdf_mode":           "light",
        },
        "debug_lab": {
            "ocr":      {"merged_text": merged_text, "confidence": ocr_conf},
            "semantic": semantic_fields,
        },
    }

    # Safe serialization
    def _safe(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        if isinstance(obj, (np.floating,)): return float(obj)
        if isinstance(obj, np.ndarray):    return obj.tolist()
        raise TypeError(f"Not serializable: {type(obj)}")

    import json
    try:
        result = json.loads(json.dumps(result, default=_safe))
    except Exception as exc:
        logger.warning("[pdf_light] Serialization warning: %s", exc)

    return result


def _fail(upload_id: str, message: str, errors: list, trace: dict) -> dict:
    return {
        "status":          "error",
        "upload_id":       upload_id,
        "message":         message,
        "errors":          errors,
        "valid_fields":    {},
        "rejected_fields": {},
        "warnings":        errors,
        "extracted_data":  {"fields": {}, "table_data": {}},
        "telemetry":       {"total_time_seconds": 0, "stage_trace": trace, "warnings": errors, "pdf_mode": "light"},
        "debug_lab":       {},
    }
