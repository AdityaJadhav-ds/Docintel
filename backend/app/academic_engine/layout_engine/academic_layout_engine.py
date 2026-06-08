"""
academic_engine/layout_engine/academic_layout_engine.py
=========================================================
STEP 3 — Layout Engine

Detects and isolates 6 document zones:

  ZONE A → Header         (top ~15%):  board, university, exam type, year
  ZONE B → Candidate      (top 15–35%): candidate name, seat number, mother name
  ZONE C → Subject table  (mid 30–70%): marks table — IGNORED in extraction
  ZONE D → Summary/Result (bottom 65–85%): percentage, CGPA, total, result
  ZONE E → Certification  (bottom 70–90%): certificate statement
  ZONE F → QR/Noise       (bottom 85–100%): QR codes, holograms — IGNORED

NOISE REGIONS (fully ignored):
  - QR codes
  - Holograms / metallic stickers
  - Decorative borders
  - Watermarks

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
import numpy as np
import cv2

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# ZONE DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Zone:
    name:        str
    label:       str
    row_start:   float  # fraction of image height (0.0–1.0)
    row_end:     float
    col_start:   float  # fraction of image width  (0.0–1.0)
    col_end:     float
    enabled:     bool   = True  # False = zone is ignored
    extraction_fields: list = field(default_factory=list)


# Base zone layout (portrait document)
_ZONES_PORTRAIT = [
    Zone("header",      "Zone A — Header",         0.00, 0.18, 0.0, 1.0, True,
         ["board_university", "passing_year", "exam_type"]),
    Zone("candidate",   "Zone B — Candidate",       0.14, 0.38, 0.0, 1.0, True,
         ["candidate_name", "passing_year"]),
    Zone("subjects",    "Zone C — Subject Table",   0.30, 0.72, 0.0, 1.0, False,   # IGNORED
         []),
    Zone("summary",     "Zone D — Summary/Result",  0.63, 0.87, 0.0, 1.0, True,
         ["percentage", "cgpa", "result", "grade_class"]),
    Zone("cert_stmt",   "Zone E — Cert Statement",  0.68, 0.92, 0.0, 1.0, True,
         ["grade_class", "result"]),
    Zone("noise",       "Zone F — QR/Noise",        0.84, 1.00, 0.0, 1.0, False,   # IGNORED
         []),
]

# Landscape layout (some mark sheets are landscape)
_ZONES_LANDSCAPE = [
    Zone("header",      "Zone A — Header",         0.00, 0.22, 0.0, 1.0, True,
         ["board_university", "passing_year"]),
    Zone("candidate",   "Zone B — Candidate",       0.18, 0.42, 0.0, 0.55, True,
         ["candidate_name"]),
    Zone("summary",     "Zone D — Summary/Result",  0.18, 0.42, 0.55, 1.0, True,
         ["percentage", "cgpa", "result"]),
    Zone("subjects",    "Zone C — Subject Table",   0.38, 0.82, 0.0, 1.0, False,
         []),
    Zone("cert_stmt",   "Zone E — Cert Statement",  0.70, 0.95, 0.0, 1.0, True,
         ["grade_class", "result"]),
    Zone("noise",       "Zone F — QR/Noise",        0.85, 1.00, 0.0, 1.0, False,
         []),
]

# ─────────────────────────────────────────────────────────────────────────────
# QR / HOLOGRAM NOISE DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def _detect_qr_regions(img: np.ndarray) -> list:
    """
    Detect QR code bounding boxes using OpenCV QR detector.
    Returns list of (x, y, w, h) tuples to mask.
    """
    regions = []
    try:
        detector = cv2.QRCodeDetector()
        gray     = img if len(img.shape) == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, pts   = detector.detect(gray)
        if pts is not None:
            for pt in pts:
                x, y, w, h = cv2.boundingRect(pt.astype(np.int32))
                pad = 10
                regions.append((max(0, x - pad), max(0, y - pad), w + 2 * pad, h + 2 * pad))
    except Exception:
        pass
    return regions


def _mask_noise_regions(img: np.ndarray) -> np.ndarray:
    """Whitewash QR codes and detected noise blobs."""
    try:
        qr_regions = _detect_qr_regions(img)
        result     = img.copy()
        for (x, y, w, h) in qr_regions:
            result[y:y+h, x:x+w] = 255
        return result
    except Exception:
        return img

# ─────────────────────────────────────────────────────────────────────────────
# LAYOUT ENGINE CLASS
# ─────────────────────────────────────────────────────────────────────────────

class AcademicLayoutEngine:
    """
    Detects document orientation and extracts ROI crops for each zone.

    Usage:
        engine = AcademicLayoutEngine()
        zones  = engine.extract_zones(img_array)
        header_roi = zones["header"]
        summary_roi = zones["summary"]
    """

    def extract_zones(
        self,
        img: np.ndarray,
        doc_category: str = "unknown",
    ) -> Dict[str, Optional[np.ndarray]]:
        """
        Extract all enabled zones as cropped image arrays.

        Args:
            img:          Full document image (BGR numpy array).
            doc_category: Classification result for zone tuning.

        Returns:
            Dict of zone_name → cropped ROI (or None if disabled/failed).
        """
        if img is None or img.size == 0:
            return {}

        # Mask QR/noise before zoning
        img = _mask_noise_regions(img)

        h, w = img.shape[:2]
        is_landscape = (w > h * 1.3)
        zones = _ZONES_LANDSCAPE if is_landscape else _ZONES_PORTRAIT

        # Tune zones for certificates (shift candidate zone up, expand cert_stmt)
        if "certificate" in doc_category:
            zones = self._tune_for_certificate(zones)

        result: Dict[str, Optional[np.ndarray]] = {}
        for zone in zones:
            if not zone.enabled:
                result[zone.name] = None
                continue

            r0 = int(zone.row_start * h)
            r1 = int(zone.row_end   * h)
            c0 = int(zone.col_start * w)
            c1 = int(zone.col_end   * w)

            # Clamp
            r0, r1 = max(0, r0), min(h, r1)
            c0, c1 = max(0, c0), min(w, c1)

            if r1 <= r0 or c1 <= c0:
                result[zone.name] = None
                continue

            roi = img[r0:r1, c0:c1]
            result[zone.name] = roi.copy()

            logger.debug("[layout] Zone '%s' → [%d:%d, %d:%d] shape=%s",
                         zone.name, r0, r1, c0, c1, roi.shape)

        return result

    @staticmethod
    def _tune_for_certificate(zones: list) -> list:
        """Adjust zone fractions for certificate documents (no marks table)."""
        tuned = []
        for z in zones:
            if z.name == "candidate":
                z = Zone(z.name, z.label, 0.12, 0.55, z.col_start, z.col_end, True, z.extraction_fields)
            if z.name == "cert_stmt":
                z = Zone(z.name, z.label, 0.40, 0.85, z.col_start, z.col_end, True, z.extraction_fields)
            tuned.append(z)
        return tuned

    def get_zone_metadata(self, img_shape: Tuple, doc_category: str = "unknown") -> Dict:
        """Return zone coordinate metadata (useful for debug overlay)."""
        h, w = img_shape[:2]
        is_landscape = (w > h * 1.3)
        zones = _ZONES_LANDSCAPE if is_landscape else _ZONES_PORTRAIT
        meta = {}
        for z in zones:
            meta[z.name] = {
                "label":   z.label,
                "enabled": z.enabled,
                "fields":  z.extraction_fields,
                "coords":  {
                    "y0": int(z.row_start * h),
                    "y1": int(z.row_end   * h),
                    "x0": int(z.col_start * w),
                    "x1": int(z.col_end   * w),
                }
            }
        return meta


# ── Singleton ──────────────────────────────────────────────────────────────────
_engine = AcademicLayoutEngine()


def extract_zones(img: np.ndarray, doc_category: str = "unknown") -> Dict[str, Optional[np.ndarray]]:
    """Module-level convenience wrapper."""
    return _engine.extract_zones(img, doc_category)


def get_zone_metadata(img_shape: Tuple, doc_category: str = "unknown") -> Dict:
    return _engine.get_zone_metadata(img_shape, doc_category)
