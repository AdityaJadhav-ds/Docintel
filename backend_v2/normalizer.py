"""
normalizer.py — Document Normalization Engine

Cleans raw OCR boxes before structure analysis.
- Fixes unicode artifacts
- Strips trailing/leading whitespace
- Filters low-confidence OCR garbage (< CONF_THRESHOLD)
- Validates box geometry (non-zero area)
"""
from layout_tree import Word
import logging

logger = logging.getLogger(__name__)

# Drop words with confidence below this threshold.
# Removes corrupted OCR fragments from dense/compressed documents.
CONF_THRESHOLD = 0.55

# Minimum word dimensions to be considered real text (pixels)
MIN_WIDTH  = 2.0
MIN_HEIGHT = 3.0


def normalize_paddle_result(raw_result) -> list:
    """Converts PaddleOCR raw output into unified Box dicts.
    Also stores confidence so normalize_boxes can filter it."""
    boxes = []
    if not raw_result:
        return boxes

    dropped = 0
    for item in raw_result:
        if len(item) == 2:
            coords, (text, conf) = item

            # Confidence filter — drop noisy OCR fragments
            if conf < CONF_THRESHOLD:
                dropped += 1
                logger.debug("Dropped low-conf word %r (%.2f)", text, conf)
                continue

            xs = [p[0] for p in coords]
            ys = [p[1] for p in coords]
            w  = max(xs) - min(xs)
            h  = max(ys) - min(ys)

            # Geometry sanity check
            if w < MIN_WIDTH or h < MIN_HEIGHT:
                dropped += 1
                continue

            boxes.append({
                "text":  text,
                "conf":  conf,
                "x1":    min(xs),
                "y1":    min(ys),
                "x2":    max(xs),
                "y2":    max(ys),
                "cx":    (min(xs) + max(xs)) / 2,
                "cy":    (min(ys) + max(ys)) / 2,
                "width": w,
                "height": h,
            })

    if dropped:
        logger.info("normalizer: dropped %d low-conf/tiny boxes", dropped)
    return boxes


def normalize_boxes(raw_boxes: list) -> list[Word]:
    """Cleans text, validates geometry, converts to Word objects."""
    cleaned = []
    for b in raw_boxes:
        text = b.get("text", "")

        # Unicode cleanup
        text = (text
                .replace("\u2013", "-").replace("\u2014", "-")
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u00a0", " ")   # non-breaking space
                )
        text = text.strip()
        if not text:
            continue

        x1 = float(b["x1"]); x2 = float(b["x2"])
        y1 = float(b["y1"]); y2 = float(b["y2"])

        if (x2 - x1) < MIN_WIDTH or (y2 - y1) < MIN_HEIGHT:
            continue

        cleaned.append(Word(
            text=text,
            x1=x1, y1=y1, x2=x2, y2=y2,
            cx=float(b["cx"]),
            cy=float(b["cy"]),
            width=x2 - x1,
            height=y2 - y1,
        ))
    return cleaned
