import fitz  # PyMuPDF
import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Default rendering DPI. 200 gives better text separation than 180
# without the memory overhead of 300.
DEFAULT_DPI   = 200
# Dense document DPI (tiny fonts, compressed bank tables)
DENSE_DPI     = 240
# DPI threshold: if page has more than this many text chars per sq inch,
# treat as dense and render at DENSE_DPI.
DENSE_CHAR_THRESHOLD = 80


def _estimate_density(page) -> bool:
    """
    Return True if the page appears to have dense/tiny text.
    Uses PyMuPDF's dict extraction to count words without rendering.
    """
    try:
        words = page.get_text("words")
        # page area in pt²  → approx sq inches at 72pt/in
        rect = page.rect
        area_in2 = (rect.width / 72.0) * (rect.height / 72.0)
        if area_in2 < 0.1:
            return False
        density = len(words) / area_in2
        return density > DENSE_CHAR_THRESHOLD
    except Exception:
        return False


def render_pdf_to_images(file_bytes: bytes, max_width: int = 1800) -> list:
    """
    Renders a PDF to a list of OpenCV images (numpy arrays).

    DPI selection:
      - Dense pages (many words, tiny font, bank tables) → DENSE_DPI (240)
      - Normal pages → DEFAULT_DPI (200)

    This avoids global DPI inflation while improving dense docs specifically.
    """
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    images = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        # Adaptive DPI
        dense = _estimate_density(page)
        dpi   = DENSE_DPI if dense else DEFAULT_DPI
        zoom  = dpi / 72.0
        mat   = fitz.Matrix(zoom, zoom)

        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert to numpy array
        img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )

        # RGB (fitz default) → BGR (OpenCV default)
        if pix.n == 3:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        elif pix.n == 1:
            img_array = cv2.cvtColor(img_array, cv2.COLOR_GRAY2BGR)

        # Hard cap width
        h, w = img_array.shape[:2]
        if w > max_width:
            scale     = max_width / w
            new_h     = int(h * scale)
            img_array = cv2.resize(img_array, (max_width, new_h), interpolation=cv2.INTER_AREA)
            logger.info("Page %d: resized from %dx%d → %dx%d (%dDPI, dense=%s)",
                        page_num + 1, w, h, max_width, new_h, dpi, dense)
        else:
            logger.info("Page %d: rendered at %dx%d (%dDPI, dense=%s)",
                        page_num + 1, w, h, dpi, dense)

        images.append(img_array)

    doc.close()
    return images
