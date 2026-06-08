"""
academic_engine/debug/academic_debug.py
=========================================
Debug Module — Saves artefacts for every processing run.

Saves to: academic_debug/<doc_id>/
  - 01_original.jpg          Original image
  - 02_restored.jpg          After restoration pipeline
  - 03_zone_<name>.jpg       Each ROI crop
  - 04_preprocessed_<name>.jpg  After ROI-specific preprocessing
  - 05_ocr_<zone>.txt        OCR output per zone
  - 06_extracted_fields.json Extracted fields dict
  - 07_confidence.json       Confidence scores
  - 08_final_output.json     Final API response

Debug mode is enabled via environment variable:
  ACADEMIC_ENGINE_DEBUG=1

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional
import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

_DEBUG_ENABLED = os.environ.get("ACADEMIC_ENGINE_DEBUG", "0").strip() == "1"
_DEBUG_ROOT    = Path(os.environ.get("ACADEMIC_DEBUG_DIR", "academic_debug_v2"))


def is_debug_enabled() -> bool:
    return _DEBUG_ENABLED


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


# ─────────────────────────────────────────────────────────────────────────────
# DEBUG SESSION
# ─────────────────────────────────────────────────────────────────────────────

class DebugSession:
    """
    Context for one document processing run.
    All artefacts saved under academic_debug/<doc_id>/
    """

    def __init__(self, doc_id: str):
        self.doc_id  = doc_id
        self.enabled = _DEBUG_ENABLED
        self.dir     = _ensure_dir(_DEBUG_ROOT / doc_id) if _DEBUG_ENABLED else None

    def save_image(self, name: str, img: np.ndarray) -> None:
        """Save a numpy array as JPEG."""
        if not self.enabled or self.dir is None or img is None or img.size == 0:
            return
        try:
            import cv2
            path = self.dir / f"{name}.jpg"
            cv2.imwrite(str(path), img)
            logger.debug("[debug] Saved image: %s", path)
        except Exception as exc:
            logger.warning("[debug] Failed to save image '%s': %s", name, exc)

    def save_text(self, name: str, text: str) -> None:
        """Save OCR text to file."""
        if not self.enabled or self.dir is None:
            return
        try:
            path = self.dir / f"{name}.txt"
            path.write_text(text or "", encoding="utf-8")
            logger.debug("[debug] Saved text: %s", path)
        except Exception as exc:
            logger.warning("[debug] Failed to save text '%s': %s", name, exc)

    def save_json(self, name: str, data: Any) -> None:
        """Save dict/list as JSON."""
        if not self.enabled or self.dir is None:
            return
        try:
            path = self.dir / f"{name}.json"
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            logger.debug("[debug] Saved JSON: %s", path)
        except Exception as exc:
            logger.warning("[debug] Failed to save JSON '%s': %s", name, exc)

    def save_all_zones(self, zones: Dict[str, Optional[np.ndarray]]) -> None:
        """Save all zone ROI crops."""
        for zone_name, roi in zones.items():
            if roi is not None and roi.size > 0:
                self.save_image(f"03_zone_{zone_name}", roi)

    def save_all_preprocessed(self, preprocessed: Dict[str, Optional[np.ndarray]]) -> None:
        """Save all preprocessed zone images."""
        for zone_name, roi in preprocessed.items():
            if roi is not None and roi.size > 0:
                self.save_image(f"04_preprocessed_{zone_name}", roi)

    def save_all_ocr_texts(self, zone_texts: Dict[str, str]) -> None:
        """Save OCR output per zone."""
        for zone_name, text in zone_texts.items():
            if text:
                self.save_text(f"05_ocr_{zone_name}", text)

    def finalize(
        self,
        original: np.ndarray,
        restored: np.ndarray,
        zones: Dict,
        preprocessed: Dict,
        zone_texts: Dict,
        extracted: Dict,
        confidence: Dict,
        final_output: Dict,
    ) -> None:
        """Save all debug artefacts for a complete processing run."""
        self.save_image("01_original", original)
        self.save_image("02_restored", restored)
        self.save_all_zones(zones)
        self.save_all_preprocessed(preprocessed)
        self.save_all_ocr_texts(zone_texts)
        self.save_json("06_extracted_fields", extracted)
        self.save_json("07_confidence", confidence)
        self.save_json("08_final_output", final_output)

        if self.enabled:
            logger.info("[debug] Debug artefacts saved to: %s", self.dir)


def create_debug_session(doc_id: str) -> DebugSession:
    """Create a new debug session for a document."""
    return DebugSession(doc_id)
