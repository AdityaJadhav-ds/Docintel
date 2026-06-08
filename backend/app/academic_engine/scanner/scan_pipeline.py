"""
academic_engine/scanner/scan_pipeline.py
=========================================
STEP 10 — Full Document Scan Pipeline Orchestrator.

Executes all restoration stages in order and saves intermediate debug frames.
Returns the original image, the final restored image, and quality metrics.

Pipeline stages:
  1. boundary_detector     → crop document from background
  2. perspective_corrector → warp + deskew + auto-rotate
  3. shadow_remover        → illumination normalisation
  4. background_cleaner    → paper whitening + JPEG artefact removal
  5. super_resolution      → upscale to ≥ 300 DPI equivalent
  6. document_enhancer     → text sharpening + final enhancement
  7. quality_analyzer      → score the final output

Debug frames are saved to:
  <project_root>/academic_debug/<timestamp>/
"""

from __future__ import annotations

import io
import os
import time
import base64
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any

import cv2
import numpy as np
from PIL import Image

from app.core.logger import logger

# ── Stage imports ─────────────────────────────────────────────────────────────
from app.academic_engine.scanner.boundary_detector    import detect_document_boundary
from app.academic_engine.scanner.perspective_corrector import correct_perspective
from app.academic_engine.scanner.shadow_remover       import remove_shadows
from app.academic_engine.scanner.background_cleaner   import clean_background
from app.academic_engine.scanner.super_resolution     import upscale_document
from app.academic_engine.scanner.document_enhancer    import enhance_document
from app.academic_engine.scanner.quality_analyzer     import analyze_quality, QualityReport


# ── Debug directory ───────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DEBUG_BASE    = _PROJECT_ROOT / "academic_debug"

SAVE_DEBUG    = os.environ.get("ACADEMIC_SCANNER_DEBUG", "true").lower() == "true"


def _save_debug(image: np.ndarray, session: str, name: str) -> Optional[Path]:
    """Save a debug frame to academic_debug/<session>/<name>.jpg"""
    if not SAVE_DEBUG:
        return None
    try:
        out_dir = DEBUG_BASE / session
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.jpg"
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
        logger.debug("[scan_pipeline] Debug frame saved: %s", path.name)
        return path
    except Exception as exc:
        logger.warning("[scan_pipeline] Could not save debug frame %s: %s", name, exc)
        return None


# ── Image conversion helpers ──────────────────────────────────────────────────

def _pil_to_bgr(pil: Image.Image) -> np.ndarray:
    rgb = np.array(pil.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def _bgr_to_pil(bgr: np.ndarray) -> Image.Image:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _bgr_to_b64(bgr: np.ndarray, quality: int = 88) -> str:
    """Encode BGR numpy image as base64 JPEG string."""
    _, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _bytes_to_bgr(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image bytes")
    return img


def _pil_to_bytes(pil: Image.Image, fmt: str = "JPEG", quality: int = 88) -> bytes:
    buf = io.BytesIO()
    pil.save(buf, format=fmt, quality=quality)
    return buf.getvalue()


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class ScanResult:
    """
    Full result of the scan pipeline.

    Attributes:
        success            : bool
        original_pil       : PIL.Image  — the input image (RGB)
        restored_pil       : PIL.Image  — the final cleaned scan (RGB)
        original_b64       : str        — base64 JPEG of original
        restored_b64       : str        — base64 JPEG of restored
        quality_report     : QualityReport
        stage_metadata     : dict       — per-stage notes (method, conf, etc.)
        debug_session      : str        — session ID for debug frames
        error              : str        — error message if success=False
        elapsed_ms         : float      — wall-clock time
    """
    success:         bool          = False
    original_pil:    Optional[Any] = None   # PIL.Image
    restored_pil:    Optional[Any] = None   # PIL.Image
    original_b64:    str           = ""
    restored_b64:    str           = ""
    quality_report:  Optional[QualityReport] = None
    stage_metadata:  Dict[str, Any] = field(default_factory=dict)
    debug_session:   str           = ""
    error:           str           = ""
    elapsed_ms:      float         = 0.0

    def to_dict(self) -> Dict[str, Any]:
        qr = self.quality_report.to_dict() if self.quality_report else {}
        return {
            "success":        self.success,
            "original_b64":   self.original_b64,
            "restored_b64":   self.restored_b64,
            "quality_report": qr,
            "stage_metadata": self.stage_metadata,
            "debug_session":  self.debug_session,
            "error":          self.error,
            "elapsed_ms":     round(self.elapsed_ms, 1),
        }


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_scan_pipeline(
    image_input,
    aggressive_enhance: bool = False,
) -> ScanResult:
    """
    Run the full document scan restoration pipeline.

    Args:
        image_input       : bytes | PIL.Image | np.ndarray (BGR)
        aggressive_enhance: If True, use stronger text enhancement.
                            Auto-enabled for very low-quality inputs.

    Returns:
        ScanResult
    """
    t0      = time.time()
    session = f"scan_{int(t0)}"
    meta: Dict[str, Any] = {}

    logger.info("[scan_pipeline] ═══ Starting scan pipeline (session=%s) ═══", session)

    # ── Normalise input to BGR numpy ──────────────────────────────────────────
    try:
        if isinstance(image_input, bytes):
            bgr = _bytes_to_bgr(image_input)
        elif isinstance(image_input, Image.Image):
            bgr = _pil_to_bgr(image_input)
        elif isinstance(image_input, np.ndarray):
            bgr = image_input.copy()
        else:
            raise ValueError(f"Unsupported image_input type: {type(image_input)}")

        original_bgr = bgr.copy()
        original_pil = _bgr_to_pil(original_bgr)
        original_b64 = _bgr_to_b64(original_bgr)
        _save_debug(original_bgr, session, "01_original")
        logger.info("[scan_pipeline] Input: %dx%d", bgr.shape[1], bgr.shape[0])

    except Exception as exc:
        logger.error("[scan_pipeline] Input normalisation failed: %s", exc)
        return ScanResult(success=False, error=f"Input error: {exc}", elapsed_ms=(time.time()-t0)*1000)

    # ── Stage 1: Boundary detection ───────────────────────────────────────────
    boundary = None   # may remain None if stage fails
    try:
        logger.info("[scan_pipeline] Stage 1: Boundary detection")
        boundary = detect_document_boundary(bgr)
        bgr      = boundary.cropped
        meta["boundary"] = {
            "method":     boundary.method,
            "confidence": boundary.confidence,
        }
        _save_debug(bgr, session, "02_boundary_cropped")
        logger.info("[scan_pipeline] ✓ Boundary: %s (conf=%.2f)", boundary.method, boundary.confidence)
    except Exception as exc:
        logger.warning("[scan_pipeline] Boundary detection failed: %s — continuing", exc)
        meta["boundary"] = {"error": str(exc)}

    # ── Stage 2: Perspective correction ──────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 2: Perspective correction")
        quad = boundary.quad if boundary is not None and boundary.quad is not None else None
        persp = correct_perspective(bgr, quad=quad)
        bgr   = persp.image
        meta["perspective"] = {
            "method":           persp.method,
            "skew_angle":       persp.skew_angle,
            "rotation_applied": persp.rotation_applied,
            "confidence":       persp.confidence,
        }
        _save_debug(bgr, session, "03_perspective_corrected")
        logger.info(
            "[scan_pipeline] ✓ Perspective: %s skew=%.1f° rot=%d°",
            persp.method, persp.skew_angle, persp.rotation_applied,
        )
    except Exception as exc:
        logger.warning("[scan_pipeline] Perspective correction failed: %s — continuing", exc)
        meta["perspective"] = {"error": str(exc)}

    # ── Stage 3: Shadow removal ───────────────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 3: Shadow removal")
        bgr = remove_shadows(bgr)
        _save_debug(bgr, session, "04_shadow_removed")
        meta["shadow_removal"] = {"status": "ok"}
        logger.info("[scan_pipeline] ✓ Shadow removal complete")
    except Exception as exc:
        logger.warning("[scan_pipeline] Shadow removal failed: %s — continuing", exc)
        meta["shadow_removal"] = {"error": str(exc)}

    # ── Stage 4: Background cleanup ───────────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 4: Background cleanup")
        bgr = clean_background(bgr)
        _save_debug(bgr, session, "05_background_cleaned")
        meta["background_cleanup"] = {"status": "ok"}
        logger.info("[scan_pipeline] ✓ Background cleanup complete")
    except Exception as exc:
        logger.warning("[scan_pipeline] Background cleanup failed: %s — continuing", exc)
        meta["background_cleanup"] = {"error": str(exc)}

    # ── Stage 5: Super resolution ─────────────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 5: Super resolution")
        bgr_sr = upscale_document(bgr)
        if bgr_sr.shape != bgr.shape:
            bgr = bgr_sr
            _save_debug(bgr, session, "06_super_resolution")
            meta["super_resolution"] = {
                "status": "upscaled",
                "output_size": f"{bgr.shape[1]}×{bgr.shape[0]}",
            }
            logger.info("[scan_pipeline] ✓ Upscaled to %dx%d", bgr.shape[1], bgr.shape[0])
        else:
            meta["super_resolution"] = {"status": "no_upscale_needed"}
            logger.info("[scan_pipeline] ✓ No upscaling needed")
    except Exception as exc:
        logger.warning("[scan_pipeline] Super resolution failed: %s — continuing", exc)
        meta["super_resolution"] = {"error": str(exc)}

    # ── Stage 6: Document enhancement ────────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 6: Document enhancement (aggressive=%s)", aggressive_enhance)
        bgr = enhance_document(bgr, aggressive=aggressive_enhance)
        _save_debug(bgr, session, "07_enhanced")
        meta["enhancement"] = {"status": "ok", "aggressive": aggressive_enhance}
        logger.info("[scan_pipeline] ✓ Enhancement complete")
    except Exception as exc:
        logger.warning("[scan_pipeline] Enhancement failed: %s — continuing", exc)
        meta["enhancement"] = {"error": str(exc)}

    # ── Final debug frame ─────────────────────────────────────────────────────
    _save_debug(bgr, session, "08_final_scan")

    # ── Stage 7: Quality analysis ─────────────────────────────────────────────
    try:
        logger.info("[scan_pipeline] Stage 7: Quality analysis")
        quality = analyze_quality(bgr)
        meta["quality"] = quality.to_dict()
        logger.info(
            "[scan_pipeline] ✓ Quality score=%.1f recommendation: %s",
            quality.quality_score, quality.recommendation,
        )

        # Auto-retry with aggressive enhance if quality < 40 and not already aggressive
        if quality.quality_score < 40 and not aggressive_enhance:
            logger.info("[scan_pipeline] Low quality — retrying with aggressive enhancement")
            bgr     = enhance_document(bgr, aggressive=True)
            quality = analyze_quality(bgr)
            meta["quality_after_retry"] = quality.to_dict()
            _save_debug(bgr, session, "09_aggressive_enhanced")

    except Exception as exc:
        logger.warning("[scan_pipeline] Quality analysis failed: %s", exc)
        quality = None
        meta["quality"] = {"error": str(exc)}

    # ── Build result ──────────────────────────────────────────────────────────
    restored_pil = _bgr_to_pil(bgr)
    restored_b64 = _bgr_to_b64(bgr)
    elapsed      = (time.time() - t0) * 1000

    logger.info(
        "[scan_pipeline] ═══ Pipeline complete in %.0fms (session=%s) ═══",
        elapsed, session,
    )

    return ScanResult(
        success        = True,
        original_pil   = original_pil,
        restored_pil   = restored_pil,
        original_b64   = original_b64,
        restored_b64   = restored_b64,
        quality_report = quality,
        stage_metadata = meta,
        debug_session  = session,
        elapsed_ms     = elapsed,
    )


# ── Convenience: accept PIL input ─────────────────────────────────────────────

def scan_pil_image(pil: Image.Image, aggressive_enhance: bool = False) -> ScanResult:
    """Convenience wrapper: accepts PIL Image, returns ScanResult."""
    return run_scan_pipeline(pil, aggressive_enhance=aggressive_enhance)


def scan_bytes(data: bytes, aggressive_enhance: bool = False) -> ScanResult:
    """Convenience wrapper: accepts raw image bytes, returns ScanResult."""
    return run_scan_pipeline(data, aggressive_enhance=aggressive_enhance)
