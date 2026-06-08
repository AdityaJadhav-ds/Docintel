"""
app/files/ingestor.py — Universal Document Ingestor
====================================================
Single entry point for ALL document uploads.

process_uploaded_document(raw_bytes, filename) → IngestedDocument

Internally:
  1. Detect file type (magic bytes)
  2. Validate (reject encrypted PDFs, executables, etc.)
  3. Convert PDF → pages OR normalise image
  4. Return structured IngestedDocument with all page images + metadata

All downstream code (OCR pipeline, validation service) should use THIS
function instead of ad-hoc PIL opens or BytesIO conversions.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np
import cv2
from PIL import Image

from app.core.logger import logger
from app.files.detector import detect, FileInfo
from app.files.normalizer import normalize_image
from app.files.pdf_converter import pdf_to_pages, PageImage, DocumentError


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class IngestedPage:
    page_num: int           # 1-indexed
    pil_image: Image.Image
    bgr_array: np.ndarray   # OpenCV BGR array for preprocessing
    is_blank: bool = False
    width: int = 0
    height: int = 0

    def __post_init__(self):
        if self.pil_image:
            self.width, self.height = self.pil_image.size


@dataclass
class IngestedDocument:
    # Input metadata
    filename: str = ""
    file_format: str = ""       # "pdf", "jpeg", "png", etc.
    mime_type: str = ""
    size_bytes: int = 0
    is_pdf: bool = False
    page_count: int = 0

    # Extracted pages (non-blank only, unless all_pages=True)
    pages: List[IngestedPage] = field(default_factory=list)
    total_pages_raw: int = 0    # includes blank pages

    # Error state
    success: bool = True
    error: Optional[str] = None
    stage: str = ""             # which stage failed: "detect", "normalize", "pdf_convert"

    @property
    def primary_page(self) -> Optional[IngestedPage]:
        """Return the best (first non-blank) page."""
        return self.pages[0] if self.pages else None

    @property
    def primary_bgr(self) -> Optional[np.ndarray]:
        """Convenience: BGR array of primary page (for OCR pipeline)."""
        p = self.primary_page
        return p.bgr_array if p else None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pil_to_bgr(img: Image.Image) -> Optional[np.ndarray]:
    """Convert PIL RGB image to OpenCV BGR array."""
    try:
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    except Exception as exc:
        logger.error("[ingestor] PIL→BGR conversion failed: %s", exc)
        return None


def _make_error(stage: str, reason: str, info: FileInfo = None) -> IngestedDocument:
    return IngestedDocument(
        success=False,
        error=reason,
        stage=stage,
        file_format=info.format if info else "",
        mime_type=info.mime if info else "",
        size_bytes=info.size_bytes if info else 0,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def process_uploaded_document(
    raw_bytes: bytes,
    filename: str = "",
    skip_blank_pages: bool = True,
) -> IngestedDocument:
    """
    Universal document ingestion entry point.

    Args:
        raw_bytes        : raw uploaded file bytes
        filename         : original filename (used for format hint)
        skip_blank_pages : exclude blank PDF pages from result (default: True)

    Returns:
        IngestedDocument — check .success before using .pages
    """
    if not raw_bytes:
        return _make_error("detect", "Empty file — 0 bytes received")

    # ── STEP 1: Detect file format ────────────────────────────────────────────
    info = detect(raw_bytes, filename=filename)
    logger.info("[ingestor] Detected: format=%s mime=%s size=%d bytes filename=%r",
                info.format, info.mime, info.size_bytes, filename)

    if info.reject_reason:
        logger.error("[ingestor] File rejected at detection: %s", info.reject_reason)
        return _make_error("detect", info.reject_reason, info)

    if not info.is_supported:
        return _make_error("detect",
                           f"Unsupported format '{info.format}'. "
                           "Accepted: PDF, JPEG, PNG, WEBP, BMP, TIFF, HEIC",
                           info)

    # ── STEP 2: PDF path ──────────────────────────────────────────────────────
    if info.is_pdf:
        return _ingest_pdf(raw_bytes, filename, info, skip_blank_pages)

    # ── STEP 3: Image path ────────────────────────────────────────────────────
    return _ingest_image(raw_bytes, filename, info)


# ── PDF ingestion ─────────────────────────────────────────────────────────────

def _ingest_pdf(
    raw_bytes: bytes,
    filename: str,
    info: FileInfo,
    skip_blank: bool,
) -> IngestedDocument:
    logger.info("[ingestor] PDF ingestion: %s", filename)

    try:
        raw_pages: List[PageImage] = pdf_to_pages(raw_bytes)
    except DocumentError as exc:
        return _make_error("pdf_convert", str(exc), info)
    except RuntimeError as exc:
        return _make_error("pdf_convert",
                           f"PDF rendering failed: {exc}. "
                           "Ensure pypdfium2 or Poppler is installed.",
                           info)
    except Exception as exc:
        return _make_error("pdf_convert", f"Unexpected PDF error: {exc}", info)

    total_raw = len(raw_pages)
    logger.info("[ingestor] PDF rendered: %d total pages", total_raw)

    pages: List[IngestedPage] = []
    for rp in raw_pages:
        if skip_blank and rp.is_blank:
            logger.debug("[ingestor] Skipping blank page %d", rp.page_num)
            continue

        # Normalise the rendered PIL image
        norm = normalize_image(
            _pil_to_bytes(rp.image),
            filename=f"{filename}_p{rp.page_num}",
            file_format="png",
        )
        if norm is None:
            logger.warning("[ingestor] Page %d normalization failed — skipping", rp.page_num)
            continue

        bgr = _pil_to_bgr(norm)
        if bgr is None:
            continue

        pages.append(IngestedPage(
            page_num=rp.page_num,
            pil_image=norm,
            bgr_array=bgr,
            is_blank=rp.is_blank,
        ))
        logger.debug("[ingestor] Page %d ingested: %dx%d", rp.page_num, norm.width, norm.height)

    if not pages:
        return _make_error("pdf_convert",
                           f"PDF rendered {total_raw} pages but all were blank or failed to normalize",
                           info)

    return IngestedDocument(
        filename=filename,
        file_format=info.format,
        mime_type=info.mime,
        size_bytes=info.size_bytes,
        is_pdf=True,
        pages=pages,
        page_count=len(pages),
        total_pages_raw=total_raw,
        success=True,
    )


# ── Image ingestion ───────────────────────────────────────────────────────────

def _ingest_image(
    raw_bytes: bytes,
    filename: str,
    info: FileInfo,
) -> IngestedDocument:
    logger.info("[ingestor] Image ingestion: format=%s filename=%s", info.format, filename)

    norm = normalize_image(raw_bytes, filename=filename, file_format=info.format)
    if norm is None:
        return _make_error("normalize",
                           f"Could not load or normalize image ({info.format}). "
                           "File may be corrupted or truncated.",
                           info)

    bgr = _pil_to_bgr(norm)
    if bgr is None:
        return _make_error("normalize", "BGR conversion failed", info)

    page = IngestedPage(page_num=1, pil_image=norm, bgr_array=bgr, is_blank=False)

    return IngestedDocument(
        filename=filename,
        file_format=info.format,
        mime_type=info.mime,
        size_bytes=info.size_bytes,
        is_pdf=False,
        pages=[page],
        page_count=1,
        total_pages_raw=1,
        success=True,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _pil_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Encode PIL Image to bytes."""
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()
