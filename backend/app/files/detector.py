"""
app/files/detector.py — Universal file type detector
=====================================================
Detects file format using magic bytes (not just extension).

Supported:
  Images : JPEG, PNG, WEBP, BMP, TIFF, HEIC/HEIF, GIF
  Docs   : PDF

Returns a FileInfo dataclass with mime, format, and validity flags.
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field
from typing import Optional

from app.core.logger import logger


# ── Magic-byte signatures ──────────────────────────────────────────────────────

_MAGIC: list[tuple[bytes, int, str, str]] = [
    # (magic, offset, mime, format_name)
    (b"\x25\x50\x44\x46",       0, "application/pdf",  "pdf"),
    (b"\xff\xd8\xff",           0, "image/jpeg",       "jpeg"),
    (b"\x89\x50\x4e\x47",      0, "image/png",        "png"),
    (b"\x52\x49\x46\x46",       0, "image/webp",       "webp"),   # RIFF....WEBP
    (b"\x42\x4d",               0, "image/bmp",        "bmp"),
    (b"\x49\x49\x2a\x00",      0, "image/tiff",       "tiff"),   # TIFF little-endian
    (b"\x4d\x4d\x00\x2a",      0, "image/tiff",       "tiff"),   # TIFF big-endian
    (b"\x47\x49\x46\x38",      0, "image/gif",        "gif"),
]

# HEIF/HEIC: "ftyp" box at offset 4, brand bytes identify HEIC
_HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"miaf", b"MiHE"}

# WEBP additional check (RIFF + "WEBP")
_WEBP_RIFF = b"RIFF"
_WEBP_MARKER = b"WEBP"

SUPPORTED_FORMATS = {"pdf", "jpeg", "png", "webp", "bmp", "tiff", "heic", "gif"}
IMAGE_FORMATS = SUPPORTED_FORMATS - {"pdf"}


@dataclass
class FileInfo:
    mime: str                   = "application/octet-stream"
    format: str                 = "unknown"
    is_pdf: bool                = False
    is_image: bool              = False
    is_heic: bool               = False
    is_supported: bool          = False
    reject_reason: Optional[str] = None
    size_bytes: int             = 0
    raw_bytes: bytes            = field(default_factory=bytes, repr=False)


def detect(data: bytes | io.BytesIO | memoryview, filename: str = "") -> FileInfo:
    """
    Detect file format from raw bytes using magic signatures.

    Args:
        data    : raw bytes, BytesIO, or memoryview
        filename: optional — used only as a last-resort hint

    Returns:
        FileInfo with detected format and validity
    """
    # Normalise to bytes
    if isinstance(data, io.BytesIO):
        data.seek(0)
        raw = data.read()
        data.seek(0)
    elif isinstance(data, memoryview):
        raw = bytes(data)
    elif isinstance(data, bytes):
        raw = data
    else:
        return FileInfo(reject_reason=f"Unsupported input type: {type(data)}")

    size = len(raw)
    if size == 0:
        return FileInfo(reject_reason="Empty file (0 bytes)", size_bytes=0)

    # ── Reject executables / dangerous formats ────────────────────────────────
    if raw[:2] == b"MZ":                   # Windows EXE / DLL
        return FileInfo(reject_reason="Executable file rejected", size_bytes=size)
    if raw[:4] == b"\x7fELF":             # Linux ELF
        return FileInfo(reject_reason="ELF binary rejected", size_bytes=size)
    if raw[:4] in (b"PK\x03\x04", b"PK\x05\x06"):  # ZIP-based (docx, apk…)
        return FileInfo(reject_reason="ZIP/Office file not supported", size_bytes=size)

    # ── HEIC / HEIF detection (ISO base media container) ─────────────────────
    if size >= 12:
        ftyp_marker = raw[4:8]
        brand       = raw[8:12]
        if ftyp_marker == b"ftyp" and brand in _HEIC_BRANDS:
            return FileInfo(
                mime="image/heic", format="heic",
                is_image=True, is_heic=True, is_supported=True,
                size_bytes=size, raw_bytes=raw,
            )

    # ── WEBP: RIFF....WEBP ───────────────────────────────────────────────────
    if size >= 12 and raw[:4] == _WEBP_RIFF and raw[8:12] == _WEBP_MARKER:
        return FileInfo(
            mime="image/webp", format="webp",
            is_image=True, is_supported=True,
            size_bytes=size, raw_bytes=raw,
        )

    # ── Standard magic signatures ─────────────────────────────────────────────
    for magic, offset, mime, fmt in _MAGIC:
        end = offset + len(magic)
        if size >= end and raw[offset:end] == magic:
            if fmt == "webp":
                # Already handled above
                continue
            is_pdf   = fmt == "pdf"
            is_image = fmt in IMAGE_FORMATS
            return FileInfo(
                mime=mime, format=fmt,
                is_pdf=is_pdf, is_image=is_image,
                is_supported=fmt in SUPPORTED_FORMATS,
                size_bytes=size, raw_bytes=raw,
            )

    # ── Last-resort: extension hint ───────────────────────────────────────────
    ext = (filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    ext_map = {
        "jpg": "jpeg", "jpeg": "jpeg", "png": "png",
        "webp": "webp", "bmp": "bmp", "tiff": "tiff", "tif": "tiff",
        "heic": "heic", "heif": "heic", "gif": "gif", "pdf": "pdf",
    }
    if ext in ext_map:
        fmt = ext_map[ext]
        is_pdf   = fmt == "pdf"
        is_image = fmt in IMAGE_FORMATS
        is_heic  = fmt == "heic"
        logger.warning("[detector] Magic bytes unrecognised — using extension hint: %s -> %s", ext, fmt)
        return FileInfo(
            mime=f"image/{fmt}" if is_image else "application/pdf",
            format=fmt,
            is_pdf=is_pdf, is_image=is_image, is_heic=is_heic,
            is_supported=fmt in SUPPORTED_FORMATS,
            size_bytes=size, raw_bytes=raw,
        )

    return FileInfo(
        reject_reason=f"Unrecognised file format (first 8 bytes: {raw[:8].hex()})",
        size_bytes=size, raw_bytes=raw,
    )
