"""
app/fraud/metadata_analyzer.py — Image metadata & origin analysis
=================================================================
Analyzes EXIF metadata, file structure, and image properties to detect:
  - Screenshot uploads (no GPS, specific dimensions, no camera data)
  - WhatsApp-forwarded images (JFIF, specific compression signatures)
  - Photoshop/editor traces (Software EXIF tag)
  - Suspicious creation timestamps
  - Missing expected camera metadata (for supposed phone photos)
"""

from __future__ import annotations
import io
import struct
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from app.core.logger import logger

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


# ── Suspicious software signatures ────────────────────────────────────────────

EDITOR_SIGNATURES = [
    "photoshop", "lightroom", "gimp", "paint", "snagit",
    "canva", "picsart", "pixlr", "facetune", "snapseed",
    "affinity", "inkscape", "paint.net", "corel",
]

SCREENSHOT_SOFTWARE = [
    "screencapture", "screenshot", "snipping", "grab",
    "scrot", "import", "prnt scr",
]

WHATSAPP_INDICATORS = [
    "whatsapp", "wa-", "img-", "vid-",
]


# ── EXIF extraction ───────────────────────────────────────────────────────────

def _extract_exif(image_input) -> Optional[Dict]:
    """Extract raw EXIF data from image."""
    if not _HAS_PIL:
        return None
    try:
        if isinstance(image_input, Image.Image):
            pil = image_input
        elif hasattr(image_input, "read"):
            pos = image_input.tell()
            pil = Image.open(image_input)
            image_input.seek(pos)
        elif isinstance(image_input, bytes):
            pil = Image.open(io.BytesIO(image_input))
        else:
            pil = Image.open(str(image_input))

        exif_data = pil._getexif() if hasattr(pil, "_getexif") else None
        if not exif_data:
            return {}
        return {TAGS.get(k, str(k)): str(v)[:200] for k, v in exif_data.items()}
    except Exception as exc:
        logger.debug("[metadata_analyzer] EXIF extraction error: %s", exc)
        return {}


def _get_pil_info(image_input) -> Dict:
    """Get PIL image info dict (format, mode, size)."""
    if not _HAS_PIL:
        return {}
    try:
        if isinstance(image_input, Image.Image):
            pil = image_input
        elif hasattr(image_input, "read"):
            pos = image_input.tell()
            pil = Image.open(image_input)
            image_input.seek(pos)
        elif isinstance(image_input, bytes):
            pil = Image.open(io.BytesIO(image_input))
        else:
            pil = Image.open(str(image_input))
        return {
            "format": pil.format or "unknown",
            "mode":   pil.mode,
            "width":  pil.size[0],
            "height": pil.size[1],
            "info":   {k: str(v)[:100] for k, v in (pil.info or {}).items()},
        }
    except Exception as exc:
        logger.debug("[metadata_analyzer] pil_info error: %s", exc)
        return {}


# ── Signal detectors ──────────────────────────────────────────────────────────

def _check_editor_software(exif: Dict) -> Tuple[Optional[str], List[str]]:
    """Check EXIF Software tag for editing tool signatures."""
    flags = []
    software = (exif.get("Software") or "").lower()
    if not software:
        return None, []

    for sig in EDITOR_SIGNATURES:
        if sig in software:
            flags.append(f"edited_with_{sig.replace(' ','_')}")
            return exif.get("Software"), flags

    for sig in SCREENSHOT_SOFTWARE:
        if sig in software:
            flags.append(f"screenshot_software_detected")
            return exif.get("Software"), flags

    return exif.get("Software"), flags


def _check_has_camera_metadata(exif: Dict) -> Tuple[bool, List[str]]:
    """Real camera photos typically have Make/Model/Flash/FocalLength."""
    flags  = []
    has_make   = bool(exif.get("Make"))
    has_model  = bool(exif.get("Model"))
    has_gps    = any("GPS" in k for k in exif)
    has_focal  = bool(exif.get("FocalLength"))

    camera_signals = sum([has_make, has_model, has_focal])
    if not exif:
        flags.append("no_exif_data")
    elif camera_signals == 0:
        flags.append("missing_camera_metadata")
    return camera_signals > 0, flags


def _check_timestamp_anomaly(exif: Dict) -> List[str]:
    """Check if EXIF DateTimeOriginal is suspicious (future date, very old)."""
    flags = []
    date_str = exif.get("DateTimeOriginal") or exif.get("DateTime") or ""
    if not date_str:
        return flags
    try:
        dt = datetime.strptime(str(date_str)[:19], "%Y:%m:%d %H:%M:%S")
        now = datetime.now()
        if dt > now:
            flags.append("future_timestamp")
        elif (now - dt).days > 365 * 5:
            flags.append("very_old_document_timestamp")
    except Exception:
        flags.append("invalid_timestamp_format")
    return flags


def _check_whatsapp_forward(pil_info: Dict) -> List[str]:
    """WhatsApp-compressed images often have specific JFIF markers."""
    flags = []
    info  = pil_info.get("info", {})
    # WhatsApp strips most EXIF but keeps JFIF header
    if pil_info.get("format") == "JPEG":
        jfif = str(info.get("jfif", "")).lower()
        if jfif:
            flags.append("jfif_header_present")
        dpi = info.get("dpi")
        if dpi and isinstance(dpi, tuple):
            # WhatsApp typically resamples to 72 DPI
            if dpi == (72, 72) or dpi == (96, 96):
                flags.append("low_dpi_resampled_possibly_whatsapp")
    return flags


def _check_image_dimensions(pil_info: Dict) -> List[str]:
    """Detect suspicious dimensions indicative of screenshots or crops."""
    flags  = []
    w, h   = pil_info.get("width", 0), pil_info.get("height", 0)
    if not w or not h:
        return flags

    # Common phone screenshot heights
    for screen_h in [1920, 2160, 2400, 2560, 1080, 720]:
        if h == screen_h or w == screen_h:
            flags.append(f"screen_resolution_dimension_{screen_h}p")
            break

    # Standard card aspect ratio ~1.586 (85.6mm × 53.98mm)
    expected_ratio = 85.6 / 54.0
    actual_ratio   = max(w, h) / max(min(w, h), 1)
    if abs(actual_ratio - expected_ratio) > 0.4:
        flags.append("non_standard_card_aspect_ratio")

    return flags


# ── Public API ────────────────────────────────────────────────────────────────

def analyze_metadata(image_input) -> Dict:
    """
    Full metadata analysis.

    Returns:
        {
            "has_exif":         bool,
            "exif_software":    str | None,
            "is_screenshot":    bool,
            "metadata_flags":   [str],
            "has_camera_data":  bool,
            "format":           str,
            "dimensions":       {width, height},
            "metadata_score":   int (0-100, higher = more suspicious)
        }
    """
    exif     = _extract_exif(image_input) or {}
    pil_info = _get_pil_info(image_input)
    flags: List[str] = []

    has_exif      = bool(exif)
    software, sw_flags = _check_editor_software(exif)
    flags.extend(sw_flags)

    has_camera, camera_flags = _check_has_camera_metadata(exif)
    flags.extend(camera_flags)

    ts_flags = _check_timestamp_anomaly(exif)
    flags.extend(ts_flags)

    wa_flags = _check_whatsapp_forward(pil_info)
    flags.extend(wa_flags)

    dim_flags = _check_image_dimensions(pil_info)
    flags.extend(dim_flags)

    # Screenshot classification
    screenshot_signals = sum([
        "screenshot_software_detected" in flags,
        "no_exif_data" in flags,
        "missing_camera_metadata" in flags,
        any("screen_resolution" in f for f in flags),
    ])
    is_screenshot = screenshot_signals >= 2

    # Metadata suspicion score (0-100)
    meta_score = 0
    if "edited_with_photoshop" in flags or any("edited_with" in f for f in flags):
        meta_score += 50
    if "screenshot_software_detected" in flags:
        meta_score += 40
    if "future_timestamp" in flags:
        meta_score += 30
    if "no_exif_data" in flags and "jfif_header_present" not in flags:
        meta_score += 20
    if "low_dpi_resampled_possibly_whatsapp" in flags:
        meta_score += 10
    meta_score = min(100, meta_score)

    logger.info(
        "[metadata_analyzer] has_exif=%s software=%r is_screenshot=%s flags=%s",
        has_exif, software, is_screenshot, flags
    )

    return {
        "has_exif":        has_exif,
        "exif_software":   software,
        "is_screenshot":   is_screenshot,
        "metadata_flags":  flags,
        "has_camera_data": has_camera,
        "format":          pil_info.get("format", "unknown"),
        "dimensions":      {
            "width":  pil_info.get("width", 0),
            "height": pil_info.get("height", 0),
        },
        "metadata_score":  meta_score,
    }
