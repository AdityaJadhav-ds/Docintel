"""
line_builder.py — OCR Box → Reading-Order Lines

Groups raw OCR boxes into horizontal lines.
Each line is a list of boxes sorted left→right, with a unified Y-center.
"""
import numpy as np
import logging

logger = logging.getLogger(__name__)


def build_lines(boxes: list) -> list:
    """
    Group OCR boxes into horizontal lines by Y-center proximity.
    Tolerance = 55% of the median box height.
    Returns: list of Line dicts
    """
    if not boxes:
        return []

    sorted_boxes = sorted(boxes, key=lambda b: b["cy"])
    heights = [b["height"] for b in sorted_boxes if b["height"] > 2]
    median_h = float(np.median(heights)) if heights else 12.0
    tol = max(5.0, median_h * 0.55)

    lines = []
    current = [sorted_boxes[0]]
    current_y = sorted_boxes[0]["cy"]

    for box in sorted_boxes[1:]:
        if abs(box["cy"] - current_y) <= tol:
            current.append(box)
            current_y = float(np.mean([b["cy"] for b in current]))
        else:
            lines.append(_make_line(current))
            current = [box]
            current_y = box["cy"]

    if current:
        lines.append(_make_line(current))

    logger.debug("build_lines: %d boxes → %d lines (tol=%.1fpx)", len(boxes), len(lines), tol)
    return lines


def _make_line(boxes: list) -> dict:
    boxes_lr = sorted(boxes, key=lambda b: b["x1"])
    x1 = min(b["x1"] for b in boxes)
    x2 = max(b["x2"] for b in boxes)
    y1 = min(b["y1"] for b in boxes)
    y2 = max(b["y2"] for b in boxes)
    cy = float(np.mean([b["cy"] for b in boxes]))
    text = " ".join(b["text"] for b in boxes_lr if b["text"].strip())
    return {
        "boxes":  boxes_lr,
        "text":   text,
        "x1": x1, "x2": x2,
        "y1": y1, "y2": y2,
        "cy": cy,
        "n_boxes": len(boxes_lr),
        "x_centers": [b["cx"] for b in boxes_lr],
    }
