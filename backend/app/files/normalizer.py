"""
app/files/normalizer.py — Universal image normalizer
=====================================================
Converts ANY supported image input into a clean, orientation-correct,
RGB PIL Image ready for OCR preprocessing.

Handles:
  - EXIF auto-rotation (mobile photos)
  - RGBA → RGB (alpha channel flattening on white bg)
  - CMYK → RGB
  - Palette ("P") → RGB
  - HEIC/HEIF via pillow-heif
  - WEBP
  - BMP, TIFF
  - Oversized images (safe downscale to max 4000px)
  - Undersized images (safe upscale to min 800px)
"""

from __future__ import annotations

import io
from typing import Optional

from PIL import Image, ImageOps
from app.core.logger import logger


# ── Constants ─────────────────────────────────────────────────────────────────

# 400 DPI PDF renders for card-sized documents are ~1300-1500px wide.
# We must NOT downscale them (blurs fine text) and NOT upscale if already large.
MAX_LONG_SIDE  = 5000   # px — hard cap to avoid OOM (5000 allows 400 DPI A4)
MIN_SHORT_SIDE = 1200   # px — upscale only if image is very small (< 1200px)


def _register_heif():
    """Register HEIF/HEIC format with Pillow if pillow-heif is available."""
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        return True
    except ImportError:
        return False


_HEIF_REGISTERED = _register_heif()


# ── EXIF orientation correction ───────────────────────────────────────────────

def _fix_exif_orientation(img: Image.Image) -> Image.Image:
    """Auto-rotate image according to EXIF orientation tag."""
    try:
        return ImageOps.exif_transpose(img)
    except Exception:
        return img


# ── Mode conversion ───────────────────────────────────────────────────────────

def _to_rgb(img: Image.Image) -> Image.Image:
    """Convert any PIL image mode to clean RGB."""
    if img.mode == "RGB":
        return img
    if img.mode == "RGBA":
        # Flatten alpha onto white background
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    if img.mode == "CMYK":
        return img.convert("RGB")
    if img.mode == "P":
        # Palette mode — convert carefully (handles transparency)
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        return bg
    if img.mode in ("L", "LA"):
        return img.convert("RGB")
    # Unknown mode — best-effort
    try:
        return img.convert("RGB")
    except Exception:
        return img


# ── Safe resize ───────────────────────────────────────────────────────────────

def _safe_resize(img: Image.Image) -> Image.Image:
    """
    Clamp image to safe dimensions for OCR:
      - Upscale if too small (short side < MIN_SHORT_SIDE)
      - Downscale if too large (long side > MAX_LONG_SIDE)
    """
    w, h = img.size
    if w == 0 or h == 0:
        return img

    long_side  = max(w, h)
    short_side = min(w, h)

    if long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
        new_w, new_h = int(w * scale), int(h * scale)
        logger.debug("[normalizer] Downscaling %dx%d -> %dx%d", w, h, new_w, new_h)
        return img.resize((new_w, new_h), Image.LANCZOS)

    if short_side < MIN_SHORT_SIDE and short_side > 0:
        scale = MIN_SHORT_SIDE / short_side
        new_w, new_h = int(w * scale), int(h * scale)
        # Cap after upscale
        if max(new_w, new_h) > MAX_LONG_SIDE:
            return img
        logger.debug("[normalizer] Upscaling %dx%d -> %dx%d", w, h, new_w, new_h)
        return img.resize((new_w, new_h), Image.LANCZOS)

    return img


# ── Public API ────────────────────────────────────────────────────────────────

def normalize_image(
    raw_bytes: bytes,
    filename: str = "",
    file_format: str = "",
) -> Optional[Image.Image]:
    """
    Load raw bytes → PIL Image → normalised RGB.

    Args:
        raw_bytes   : raw file bytes (any supported format)
        filename    : optional filename hint
        file_format : optional format hint ("jpeg", "png", "heic", etc.)

    Returns:
        Normalised PIL RGB Image, or None on failure.
    """
    if not raw_bytes:
        logger.error("[normalizer] Empty bytes — nothing to normalize")
        return None

    # ── Load image ────────────────────────────────────────────────────────────
    img: Optional[Image.Image] = None

    # HEIC requires pillow-heif to be registered first
    if file_format == "heic" and not _HEIF_REGISTERED:
        logger.error("[normalizer] HEIC/HEIF requires pillow-heif — not installed")
        return None

    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()  # Force decode now to catch truncated files early
    except Exception as exc:
        logger.error("[normalizer] PIL failed to open image: %s", exc)
        return None

    logger.debug("[normalizer] Loaded: mode=%s size=%s format=%s file=%s",
                 img.mode, img.size, img.format, filename)

    # ── EXIF orientation ──────────────────────────────────────────────────────
    img = _fix_exif_orientation(img)

    # ── Mode → RGB ────────────────────────────────────────────────────────────
    img = _to_rgb(img)

    # ── Safe resize ───────────────────────────────────────────────────────────
    img = _safe_resize(img)

    logger.debug("[normalizer] Normalised: size=%s mode=%s", img.size, img.mode)
    return img
