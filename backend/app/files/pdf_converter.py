"""
app/files/pdf_converter.py — Production PDF → image pages converter
====================================================================
Renders each page of a PDF at 400 DPI using the best available engine.

CRITICAL FIX (2026-05-07):
  pypdfium2 renders in BGRx by default. to_pil() WITHOUT rev_byteorder=True
  treats the BGRx buffer as RGBx — swapping R and B channels completely.
  This produces visually distorted (color-mangled) images that destroy OCR.
  Fix: pass rev_byteorder=True to page.render() to get correct RGB output.

Engine priority:
  1. pypdfium2  — pure Python, no system deps, fast, now correctly RGB
  2. pdf2image  — requires Poppler system install
  3. PyMuPDF    — fallback if fitz is available

Key settings (OCR-critical):
  - 400 DPI (card-sized PDFs need this; 300 DPI renders too small)
  - rev_byteorder=True → correct RGB output from pypdfium2
  - White fill_color background (transparent areas → white, not black)
  - optimize_mode="print" → sharpest text for OCR
  - Debug save to logs/pdf_debug/ (set PDF_SAVE_DEBUG=true)
"""

from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PIL import Image
from app.core.logger import logger


# ── DPI / scale settings ──────────────────────────────────────────────────────

# 400 DPI = scale 5.556 for pypdfium2 (pixels per PDF point, 1pt = 1/72 inch)
# A PAN card PDF at ~242x153 pts → 1345x851 px at 400 DPI — sharp enough for OCR
PDF_DPI   = 400
PDF_SCALE = PDF_DPI / 72.0   # 5.5555...

BLANK_PAGE_THRESHOLD = 252   # mean pixel > 252 on L channel = blank
MAX_PAGES = 20

# Enable debug page saving via env var
PDF_SAVE_DEBUG = os.getenv("PDF_SAVE_DEBUG", "false").lower() == "true"
_PDF_DEBUG_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "pdf_debug"


# ── Errors ────────────────────────────────────────────────────────────────────

class DocumentError(Exception):
    """Raised for unrecoverable document issues (encrypted, corrupt, etc.)."""


@dataclass
class PageImage:
    page_num: int
    image: Image.Image
    is_blank: bool = False
    width: int = 0
    height: int = 0
    engine: str = ""

    def __post_init__(self):
        if self.image:
            self.width, self.height = self.image.size


# ── Debug page saving ─────────────────────────────────────────────────────────

def _save_debug_page(img: Image.Image, page_num: int, engine: str) -> None:
    if not PDF_SAVE_DEBUG:
        return
    try:
        _PDF_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts   = int(time.time())
        path = _PDF_DEBUG_DIR / f"page_{ts}_p{page_num}_{engine}.png"
        img.save(str(path))
        logger.info("[pdf_converter] Debug page saved: %s (%dx%d)", path.name, img.width, img.height)
    except Exception as exc:
        logger.warning("[pdf_converter] Could not save debug page: %s", exc)


# ── Blank page detection ──────────────────────────────────────────────────────

def _is_blank(img: Image.Image) -> bool:
    try:
        import numpy as np
        return float(np.array(img.convert("L")).mean()) > BLANK_PAGE_THRESHOLD
    except Exception:
        return False


# ── Engine 1: pypdfium2 ───────────────────────────────────────────────────────

def _render_with_pypdfium2(pdf_bytes: bytes) -> List[PageImage]:
    """
    Render PDF pages using pypdfium2 with correct RGB channel order.

    THE BUG: pypdfium2's default render() produces BGRx pixels.
    to_pil() without rev_byteorder=True interprets them as RGBx, swapping
    Red and Blue channels — turning white text on blue into blue text on red.
    This is visually devastating for OCR.

    THE FIX: rev_byteorder=True makes render() produce RGBx instead of BGRx,
    so to_pil() returns a correct RGB image.
    """
    import pypdfium2 as pdfium

    doc     = pdfium.PdfDocument(pdf_bytes)
    n_pages = len(doc)
    logger.info("[pdf_converter] pypdfium2: %d pages, scale=%.3f (~%d DPI)", n_pages, PDF_SCALE, PDF_DPI)

    # Early encryption check
    try:
        _ = doc[0]
    except Exception as exc:
        if any(k in str(exc).lower() for k in ("password", "encrypt", "locked")):
            raise DocumentError("PDF is password-protected / encrypted")
        raise

    pages: List[PageImage] = []
    for i in range(min(n_pages, MAX_PAGES)):
        try:
            page = doc[i]
            w_pt = page.get_width()
            h_pt = page.get_height()

            bitmap = page.render(
                scale=PDF_SCALE,
                rotation=0,
                # ┌─ CRITICAL BUG FIX ─────────────────────────────────────┐
                # pypdfium2 default = BGRx bytes. to_pil() reads as RGBx.  │
                # rev_byteorder=True → render produces RGBx → correct PIL. │
                rev_byteorder=True,
                # └────────────────────────────────────────────────────────┘
                fill_color=(255, 255, 255, 255),   # white background
                optimize_mode="print",             # sharpest text for OCR
                no_smoothtext=False,               # keep AA for text
                no_smoothimage=False,              # keep AA for images
            )

            # to_pil() is now safe — buffer is RGBx
            pil = bitmap.to_pil()

            # Force to plain RGB (handle RGBA, L, or any other mode)
            if pil.mode == "RGBA":
                bg = Image.new("RGB", pil.size, (255, 255, 255))
                bg.paste(pil, mask=pil.split()[3])
                pil = bg
            elif pil.mode != "RGB":
                pil = pil.convert("RGB")

            blank = _is_blank(pil)
            logger.info(
                "[pdf_converter] pypdfium2 page %d: %.1fpt×%.1fpt → %dx%d px  mode=%s  blank=%s",
                i + 1, w_pt, h_pt, pil.width, pil.height, pil.mode, blank
            )
            _save_debug_page(pil, i + 1, "pypdfium2")
            pages.append(PageImage(page_num=i + 1, image=pil, is_blank=blank, engine="pypdfium2"))

        except DocumentError:
            raise
        except Exception as exc:
            logger.warning("[pdf_converter] pypdfium2 page %d failed: %s", i + 1, exc)

    if not pages:
        raise DocumentError("pypdfium2 rendered 0 usable pages")
    return pages


# ── Engine 2: pdf2image / Poppler ─────────────────────────────────────────────

def _get_poppler_path() -> Optional[str]:
    import os as _os
    try:
        from app.core.config import config as _cfg
        p = getattr(_cfg, "POPPLER_PATH", "").strip()
        if p and _os.path.isdir(p):
            return p
    except Exception:
        pass
    p = _os.environ.get("POPPLER_PATH", "").strip()
    if p and _os.path.isdir(p):
        return p
    for fb in [r"C:\poppler\Library\bin", r"C:\poppler\bin"]:
        if _os.path.isdir(fb):
            return fb
    return None


def _render_with_pdf2image(pdf_bytes: bytes) -> List[PageImage]:
    from pdf2image import convert_from_bytes
    kw: dict = {"dpi": PDF_DPI, "fmt": "png", "thread_count": 1}
    poppler = _get_poppler_path()
    if poppler:
        kw["poppler_path"] = poppler

    pil_pages = convert_from_bytes(pdf_bytes, **kw)[:MAX_PAGES]
    logger.info("[pdf_converter] pdf2image: %d pages at %d DPI", len(pil_pages), PDF_DPI)

    pages: List[PageImage] = []
    for i, pil in enumerate(pil_pages):
        pil   = pil.convert("RGB")
        blank = _is_blank(pil)
        logger.info("[pdf_converter] pdf2image page %d: %dx%d blank=%s", i + 1, pil.width, pil.height, blank)
        _save_debug_page(pil, i + 1, "pdf2image")
        pages.append(PageImage(page_num=i + 1, image=pil, is_blank=blank, engine="pdf2image"))
    return pages


# ── Engine 3: PyMuPDF ─────────────────────────────────────────────────────────

def _render_with_pymupdf(pdf_bytes: bytes) -> List[PageImage]:
    import fitz
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.is_encrypted:
        raise DocumentError("PDF is password-protected / encrypted")
    n   = min(doc.page_count, MAX_PAGES)
    mat = fitz.Matrix(PDF_SCALE, PDF_SCALE)
    logger.info("[pdf_converter] PyMuPDF: %d pages at %.3f scale", n, PDF_SCALE)

    pages: List[PageImage] = []
    for i in range(n):
        page = doc[i]
        pix  = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
        pil  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        blank = _is_blank(pil)
        logger.info("[pdf_converter] PyMuPDF page %d: %dx%d blank=%s", i + 1, pil.width, pil.height, blank)
        _save_debug_page(pil, i + 1, "pymupdf")
        pages.append(PageImage(page_num=i + 1, image=pil, is_blank=blank, engine="pymupdf"))
    return pages


# ── Public API ────────────────────────────────────────────────────────────────

def pdf_to_pages(pdf_input) -> List[PageImage]:
    """
    Convert a PDF to a list of PageImage objects.

    Args:
        pdf_input: bytes | BytesIO | file path (str)

    Returns:
        List[PageImage] with .image (PIL RGB), .is_blank, .page_num

    Raises:
        DocumentError  — encrypted, corrupt, unreadable PDF
        RuntimeError   — all engines failed
    """
    # Normalise to bytes
    if isinstance(pdf_input, str):
        with open(pdf_input, "rb") as f:
            pdf_bytes = f.read()
    elif hasattr(pdf_input, "read"):
        if hasattr(pdf_input, "seek"):
            pdf_input.seek(0)
        pdf_bytes = pdf_input.read()
        if hasattr(pdf_input, "seek"):
            pdf_input.seek(0)
    elif isinstance(pdf_input, bytes):
        pdf_bytes = pdf_input
    else:
        raise ValueError(f"Unsupported pdf_input type: {type(pdf_input)}")

    if not pdf_bytes:
        raise DocumentError("PDF bytes are empty")
    if pdf_bytes[:4] != b"%PDF":
        raise DocumentError(f"Not a valid PDF (magic: {pdf_bytes[:4]!r})")

    logger.info("[pdf_converter] PDF: %d bytes — target %d DPI (scale=%.3f)",
                len(pdf_bytes), PDF_DPI, PDF_SCALE)

    errors: list = []

    # Engine 1: pypdfium2
    try:
        pages = _render_with_pypdfium2(pdf_bytes)
        logger.info("[pdf_converter] ✓ pypdfium2 → %d pages", len(pages))
        return pages
    except DocumentError:
        raise
    except Exception as exc:
        logger.warning("[pdf_converter] pypdfium2 failed: %s", exc)
        errors.append(f"pypdfium2: {exc}")

    # Engine 2: pdf2image
    try:
        pages = _render_with_pdf2image(pdf_bytes)
        logger.info("[pdf_converter] ✓ pdf2image → %d pages", len(pages))
        return pages
    except ImportError:
        logger.debug("[pdf_converter] pdf2image not installed")
    except DocumentError:
        raise
    except Exception as exc:
        logger.warning("[pdf_converter] pdf2image failed: %s", exc)
        errors.append(f"pdf2image: {exc}")

    # Engine 3: PyMuPDF
    try:
        pages = _render_with_pymupdf(pdf_bytes)
        logger.info("[pdf_converter] ✓ PyMuPDF → %d pages", len(pages))
        return pages
    except ImportError:
        logger.debug("[pdf_converter] fitz (PyMuPDF) not installed")
    except DocumentError:
        raise
    except Exception as exc:
        logger.warning("[pdf_converter] PyMuPDF failed: %s", exc)
        errors.append(f"pymupdf: {exc}")

    raise RuntimeError(
        f"All PDF engines failed: {'; '.join(errors)}. "
        "Install pypdfium2: pip install pypdfium2"
    )


def pdf_first_page(pdf_input) -> Optional[Image.Image]:
    """Return first non-blank page as PIL RGB Image."""
    try:
        pages = pdf_to_pages(pdf_input)
        for p in pages:
            if not p.is_blank:
                return p.image
        return pages[0].image if pages else None
    except Exception as exc:
        logger.error("[pdf_converter] pdf_first_page failed: %s", exc)
        return None


# ── Backward-compatible shims ─────────────────────────────────────────────────

def pdf_to_image(pdf_input) -> Optional[Image.Image]:
    """Legacy shim — returns first page PIL Image."""
    return pdf_first_page(pdf_input)


def is_pdf(data) -> bool:
    """Quick magic-byte check for PDF."""
    if isinstance(data, str):
        return data.lower().endswith(".pdf")
    if hasattr(data, "read"):
        hdr = data.read(4)
        if hasattr(data, "seek"):
            data.seek(0)
        return hdr == b"%PDF"
    if isinstance(data, bytes):
        return data[:4] == b"%PDF"
    return False
