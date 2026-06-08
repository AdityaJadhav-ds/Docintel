"""
response_builder.py — Layer 1 + Stage 2: Positional Line Reconstruction

Each line now carries THREE representations:
  1. text           — plain joined words (Stage 1, always works)
  2. positioned_text — X-space-padded string (Stage 2, visual column alignment)
  3. words          — individual word positions for frontend exact rendering

positioned_text algorithm:
  char_width = page_width / COLS   (COLS = target character columns, default 120)
  for each word (sorted left→right):
      char_pos = int(word.x1 / char_width)
      insert word.text at char_pos in buffer
  join buffer → strip trailing spaces

This reconstructs visual layout WITHOUT tables, WITHOUT column detection,
WITHOUT semantic parsing. Pure geometry.
"""
from layout_tree import Document
import logging

logger = logging.getLogger(__name__)

# Fallback char width (px) if too few words to estimate
FALLBACK_CHAR_W = 8.0

# Hard limits to prevent extreme grids
MIN_CHAR_W = 4.0
MAX_CHAR_W = 18.0


def _estimate_char_width(words) -> float:
    """
    Estimate the average character width in pixels from actual OCR word data.
    Uses: avg_word_pixel_width / avg_word_char_count
    Falls back to FALLBACK_CHAR_W if too few data points.

    This is far more accurate than page_width/120 on dense docs
    where characters may be only 5-6px wide.
    """
    samples = []
    for w in words:
        char_count = len(w.text.strip())
        px_width   = w.width
        if char_count >= 2 and px_width > 4:
            samples.append(px_width / char_count)

    if len(samples) < 5:
        return FALLBACK_CHAR_W

    # Use median to resist outliers (very wide or very narrow words)
    import numpy as np
    cw = float(np.median(samples))
    return float(min(max(cw, MIN_CHAR_W), MAX_CHAR_W))

def _build_positioned_text(words, char_w: float) -> str:
    """
    Convert word positions into a space-padded string using adaptive
    char_w (px per character), computed per page from actual word metrics.

    Example (char_w=7.5px, page words at x1=50,280,680):
      col(02Feb)=6, col(UPI/ABC)=37, col(663.00)=90
      → "      02Feb                         UPI/ABC                      663.00"
    """
    if not words:
        return ""

    # Use the adaptive char_w passed in (computed per page)
    if char_w <= 0:
        char_w = FALLBACK_CHAR_W

    # Build position → text map (left-to-right, skip empty)
    slots = {}
    for word in sorted(words, key=lambda w: w.x1):
        if not word.text.strip():
            continue
        col = max(0, int(word.x1 / char_w))
        slots[col] = word.text

    if not slots:
        return ""

    # Find total buffer length needed
    max_end = max(col + len(text) for col, text in slots.items())
    buf = [" "] * (max_end + 1)

    # Write words into buffer, right-neighbour truncation if overlap
    for col, text in sorted(slots.items()):
        for j, ch in enumerate(text):
            idx = col + j
            if idx < len(buf):
                buf[idx] = ch

    return "".join(buf).rstrip()


def build_response(
    doc: Document,
    filename: str,
    run_id: str,
    preview_urls: list[str],
    perf: dict,
) -> dict:

    all_lines   = []
    all_text    = []
    total_words = 0
    page_dims   = {}

    for page in doc.pages:
        total_words += len(page.words)

        if page.page_number == 1:
            page_dims = {"width": page.width, "height": page.height}

        pw     = float(page.width) if page.width else 1200.0

        # Adaptive char width: derived from actual word metrics on this page
        char_w = _estimate_char_width(page.words)

        sorted_lines = sorted(page.lines, key=lambda l: l.cy)

        for line in sorted_lines:
            if not line.text.strip():
                continue

            vlines = line.visual_lines if getattr(line, 'visual_lines', None) else [line]
            
            logical_row = []
            row_positioned_texts = []
            
            for vl in vlines:
                pos_text = _build_positioned_text(vl.words, char_w)
                row_positioned_texts.append(pos_text)
                logical_row.append({
                    "text": vl.text,
                    "positioned_text": pos_text,
                    "words": [
                        {
                            "text": w.text,
                            "x1": round(w.x1, 1),
                            "x2": round(w.x2, 1),
                            "y1": round(w.y1, 1),
                            "y2": round(w.y2, 1),
                        }
                        for w in sorted(vl.words, key=lambda w: w.x1) if w.text.strip()
                    ],
                    "y": round(vl.cy, 1)
                })

            # Stage 2: positional text for the whole logical row (joined by newline)
            positioned = "\n".join(row_positioned_texts)

            # Flat word list for exact renderer (Stage 3)
            word_spans = [
                {
                    "text": w.text,
                    "x1":   round(w.x1, 1),
                    "x2":   round(w.x2, 1),
                    "y1":   round(w.y1, 1),
                    "y2":   round(w.y2, 1),
                }
                for w in sorted(line.words, key=lambda w: w.x1)
                if w.text.strip()
            ]

            all_lines.append({
                "line_id":         line.line_id,
                "page":            page.page_number - 1,
                "text":            line.text,           # Stage 1: plain
                "positioned_text": positioned,           # Stage 2: x-aligned (multiline)
                "logical_row":     logical_row,          # Sub-lines for visual rendering
                "region_type":     getattr(line, "region_type", "paragraph"),
                "words":           word_spans,           # Stage 3: per-word spans
                "y":               round(line.cy, 1),
                "x1":              round(line.x1, 1),
                "y1":              round(line.y1, 1),
                "x2":              round(line.x2, 1),
                "y2":              round(line.y2, 1),
            })
            all_text.append(positioned)  # clean_text uses positional form

    clean_text = "\n".join(all_text)

    logger.info(
        "response_builder: %d pages → %d lines → %d words",
        len(doc.pages), len(all_lines), total_words
    )

    return {
        "success":        True,
        "overall_status": "done",
        "pipeline":       "layer1_positional",

        "preview_url": preview_urls[0] if preview_urls else "",
        "images":      {"pages": preview_urls},

        "lines":      all_lines,
        "clean_text": clean_text,

        "page_dims":  page_dims,

        "word_count": total_words,
        "elapsed_ms": perf.get("total_ms", 0),

        "metadata": {
            "filename":         filename,
            "page_count":       len(doc.pages),
            "total_elapsed_ms": perf.get("total_ms", 0),
            "line_count":       len(all_lines),
        },
        "ocr":      {"word_count": total_words},
        "perf_log": perf,
        "error":    "",

        # Legacy empty fields
        "blocks":       [],
        "transactions": [],
        "tables":       [],
        "document":     doc.to_dict(),
    }
