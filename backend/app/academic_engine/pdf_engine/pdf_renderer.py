"""
pdf_engine/pdf_renderer.py
===========================
STEP 2 — High-quality PDF page renderer.

PRIMARY:   PyMuPDF (fitz)     — zoom=4.0 → ~400 DPI (72dpi base × 4 = 288; zoom=5.56 → 400)
FALLBACK1: pypdfium2          — scale=_TARGET_DPI/72 ≈ 5.56
FALLBACK2: pdf2image/poppler  — dpi=400

Renders at 400 DPI minimum — NEVER below 300 DPI.

Returns:
    List[dict]:
        {
            "page_number": int,        # 1-indexed
            "image":       np.ndarray, # BGR uint8
            "width":       int,
            "height":      int,
            "dpi":         int,
            "engine":      str,        # "fitz" | "pypdfium2" | "pdf2image"
        }
"""
from __future__ import annotations

import logging
from typing import List

import cv2
import numpy as np

logger = logging.getLogger("docvalidator")

# ── DPI / zoom constants ──────────────────────────────────────────────────────
# PyMuPDF (fitz): internal base = 72 dpi.
#   zoom = 5.56 → 72 × 5.56 ≈ 400 dpi  ← robust OCR resolution for bank statements
_TARGET_DPI   = 400
_FITZ_ZOOM    = _TARGET_DPI / 72.0       # ≈ 5.56 for 400 DPI
_FITZ_MIN_ZOOM = 200 / 72.0              # ≈ 2.78  minimum acceptable
# pypdfium2 uses same 72-dpi base
_PYPDFIUM_SCALE = _TARGET_DPI / 72.0
_MAX_SCALE      = 6.0                    # safety cap


# ═══════════════════════════════════════════════════════════════════════════════
# PRIMARY ENGINE — PyMuPDF (fitz)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_with_fitz(pdf_bytes: bytes) -> List[dict]:
    """
    Primary renderer using PyMuPDF (fitz).

    Uses a zoom Matrix for precise DPI control:
        zoom = 5.56  → 72 × 5.56 ≈ 400 DPI
        matrix = fitz.Matrix(zoom, zoom)

    Produces BGR numpy arrays ready for OpenCV/OCR pipeline.
    """
    import fitz  # PyMuPDF

    pages_out: List[dict] = []
    zoom = min(_FITZ_ZOOM, _MAX_SCALE)
    matrix = fitz.Matrix(zoom, zoom)

    # Open from bytes
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    n_pages = len(pdf)

    logger.info(
        "[pdf_renderer] fitz: %d page(s), zoom=%.3f (~%d DPI)",
        n_pages, zoom, _TARGET_DPI,
    )

    for idx in range(n_pages):
        try:
            page = pdf[idx]

            # Render page to pixmap at target resolution
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)

            # Pixmap → numpy array (RGB)
            img_rgb = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )

            # Convert to BGR for OpenCV
            if pixmap.n == 3:  # RGB
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            elif pixmap.n == 4:  # RGBA
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGBA2BGR)
            elif pixmap.n == 1:  # grayscale
                img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_GRAY2BGR)
            else:
                img_bgr = img_rgb  # fallback

            h, w = img_bgr.shape[:2]
            pages_out.append({
                "page_number": idx + 1,
                "image":       img_bgr,
                "width":       w,
                "height":      h,
                "dpi":         _TARGET_DPI,
                "engine":      "fitz",
            })
            logger.info("[pdf_renderer] fitz page %d: %dx%d px", idx + 1, w, h)

        except Exception as exc:
            logger.warning("[pdf_renderer] fitz failed page %d: %s", idx + 1, exc)

    pdf.close()
    return pages_out


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK 1 — pypdfium2
# ═══════════════════════════════════════════════════════════════════════════════

def _render_with_pypdfium2(pdf_bytes: bytes) -> List[dict]:
    """Secondary renderer — uses pypdfium2, zero external binary needed."""
    import pypdfium2 as pdfium

    pages_out: List[dict] = []
    pdf = pdfium.PdfDocument(pdf_bytes)
    n_pages = len(pdf)
    scale = min(_PYPDFIUM_SCALE, _MAX_SCALE)

    logger.info(
        "[pdf_renderer] pypdfium2: %d page(s), scale=%.2f (~%d DPI)",
        n_pages, scale, _TARGET_DPI,
    )

    for idx in range(n_pages):
        try:
            page = pdf[idx]
            bitmap = page.render(scale=scale, rotation=0)
            pil_img = bitmap.to_pil()

            img_rgb = np.array(pil_img.convert("RGB"))
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            h, w = img_bgr.shape[:2]

            pages_out.append({
                "page_number": idx + 1,
                "image":       img_bgr,
                "width":       w,
                "height":      h,
                "dpi":         _TARGET_DPI,
                "engine":      "pypdfium2",
            })
            logger.info("[pdf_renderer] pypdfium2 page %d: %dx%d px", idx + 1, w, h)

        except Exception as exc:
            logger.warning("[pdf_renderer] pypdfium2 failed page %d: %s", idx + 1, exc)

    pdf.close()
    return pages_out


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK 2 — pdf2image (Poppler)
# ═══════════════════════════════════════════════════════════════════════════════

def _render_with_pdf2image(pdf_bytes: bytes) -> List[dict]:
    """Tertiary fallback — uses pdf2image + Poppler binary."""
    from pdf2image import convert_from_bytes

    logger.info("[pdf_renderer] pdf2image fallback at %d DPI", _TARGET_DPI)
    pil_pages = convert_from_bytes(pdf_bytes, dpi=_TARGET_DPI, fmt="png")

    pages_out: List[dict] = []
    for idx, pil_img in enumerate(pil_pages):
        try:
            img_rgb = np.array(pil_img.convert("RGB"))
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            h, w = img_bgr.shape[:2]
            pages_out.append({
                "page_number": idx + 1,
                "image":       img_bgr,
                "width":       w,
                "height":      h,
                "dpi":         _TARGET_DPI,
                "engine":      "pdf2image",
            })
            logger.info("[pdf_renderer] pdf2image page %d: %dx%d px", idx + 1, w, h)
        except Exception as exc:
            logger.warning("[pdf_renderer] pdf2image failed page %d: %s", idx + 1, exc)

    return pages_out


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════════════════════

def render_pdf_pages(pdf_bytes: bytes) -> List[dict]:
    """
    Render ALL pages of a PDF into high-quality numpy images (BGR).

    Engine priority:
        1. PyMuPDF (fitz)   — primary (zoom matrix, 400 DPI)
        2. pypdfium2         — fallback 1
        3. pdf2image/poppler — fallback 2

    Never returns pages below 300 DPI.
    Returns [] if all engines fail.

    Args:
        pdf_bytes: raw PDF file bytes

    Returns:
        List of page dicts: {page_number, image, width, height, dpi, engine}
    """
    if not pdf_bytes:
        logger.error("[pdf_renderer] Empty PDF bytes received")
        return []

    if pdf_bytes[:4] != b"%PDF":
        logger.error("[pdf_renderer] Invalid PDF header (not a PDF)")
        return []

    # ── Engine 1: PyMuPDF (fitz) ─────────────────────────────────────────────
    try:
        pages = _render_with_fitz(pdf_bytes)
        if pages:
            logger.info("[pdf_renderer] fitz rendered %d pages OK", len(pages))
            return pages
        logger.warning("[pdf_renderer] fitz returned 0 pages — trying pypdfium2")
    except ImportError:
        logger.warning("[pdf_renderer] PyMuPDF not available — trying pypdfium2")
    except Exception as exc:
        logger.warning("[pdf_renderer] fitz error: %s — trying pypdfium2", exc)

    # ── Engine 2: pypdfium2 ───────────────────────────────────────────────────
    try:
        pages = _render_with_pypdfium2(pdf_bytes)
        if pages:
            logger.info("[pdf_renderer] pypdfium2 rendered %d pages OK", len(pages))
            return pages
        logger.warning("[pdf_renderer] pypdfium2 returned 0 pages — trying pdf2image")
    except ImportError:
        logger.warning("[pdf_renderer] pypdfium2 not available — trying pdf2image")
    except Exception as exc:
        logger.warning("[pdf_renderer] pypdfium2 error: %s — trying pdf2image", exc)

    # ── Engine 3: pdf2image ───────────────────────────────────────────────────
    try:
        pages = _render_with_pdf2image(pdf_bytes)
        if pages:
            logger.info("[pdf_renderer] pdf2image rendered %d pages OK", len(pages))
            return pages
    except ImportError:
        logger.error("[pdf_renderer] pdf2image unavailable — install pdf2image + poppler")
    except Exception as exc:
        logger.error("[pdf_renderer] pdf2image error: %s", exc)

    logger.error("[pdf_renderer] ALL engines failed — PDF cannot be rendered")
    return []


def extract_native_text(pdf_bytes: bytes) -> str:
    """
    Extract embedded text from a digital PDF (no OCR).
    Returns empty string for scanned PDFs.

    Used alongside rendered images — even if text is extracted here,
    we STILL render the image for the vision/OCR pipeline.

    Priority: fitz → pypdfium2 → pdfplumber
    """
    # ── fitz (most reliable) ─────────────────────────────────────────────────
    try:
        import fitz
        pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
        texts = []
        for page in pdf:
            texts.append(page.get_text("text"))
        pdf.close()
        result = "\n".join(texts).strip()
        if result:
            logger.debug("[pdf_renderer] fitz native text: %d chars", len(result))
            return result
    except Exception as exc:
        logger.debug("[pdf_renderer] fitz text extraction: %s", exc)

    # ── pypdfium2 ─────────────────────────────────────────────────────────────
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_bytes)
        texts = []
        for idx in range(len(pdf)):
            page = pdf[idx]
            textpage = page.get_textpage()
            texts.append(textpage.get_text_range())
            textpage.close()
        pdf.close()
        result = "\n".join(texts).strip()
        if result:
            return result
    except Exception as exc:
        logger.debug("[pdf_renderer] pypdfium2 text extraction: %s", exc)

    # ── pdfplumber fallback ───────────────────────────────────────────────────
    try:
        import io
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(
                (p.extract_text() or "") for p in pdf.pages
            ).strip()
    except Exception:
        pass

    return ""
