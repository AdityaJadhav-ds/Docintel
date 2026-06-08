"""
layout_engine.py — Universal Layout Analysis Engine

Pure geometry. No bank names. No regex. No document type detection.
Works on OCR boxes from any document.

PIPELINE:
  boxes[] → rows[] → column_anchors[] → grid[][] → blocks[]
"""

import numpy as np
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Row Detection
# Group OCR boxes into horizontal lines by Y-center proximity
# ─────────────────────────────────────────────────────────────────────────────

def detect_rows(boxes: list) -> list:
    """
    Group OCR boxes into rows by Y-center proximity.
    Tolerance = 50% of the median box height.
    Returns list of rows, each row is a list of boxes sorted left→right.
    """
    if not boxes:
        return []

    sorted_boxes = sorted(boxes, key=lambda b: b["cy"])
    heights = [b["height"] for b in sorted_boxes if b["height"] > 0]
    median_h = float(np.median(heights)) if heights else 12.0
    tol = max(6.0, median_h * 0.55)  # at least 6px tolerance

    rows = []
    current_row = [sorted_boxes[0]]
    current_y = sorted_boxes[0]["cy"]

    for box in sorted_boxes[1:]:
        if abs(box["cy"] - current_y) <= tol:
            current_row.append(box)
            # Keep running Y average to stay stable across wide rows
            current_y = float(np.mean([b["cy"] for b in current_row]))
        else:
            rows.append(sorted(current_row, key=lambda b: b["x1"]))
            current_row = [box]
            current_y = box["cy"]

    if current_row:
        rows.append(sorted(current_row, key=lambda b: b["x1"]))

    logger.debug("detect_rows: %d boxes → %d rows (tol=%.1f)", len(boxes), len(rows), tol)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Column Detection
# Find vertical column boundaries using projection gap analysis
# ─────────────────────────────────────────────────────────────────────────────

def detect_columns(rows: list, page_width: int = 1488, min_gap: int = 20) -> list:
    """
    Find column boundary positions by projecting all box X-extents
    onto the horizontal axis and finding empty (gap) regions.

    Returns list of (x_left, x_right) tuples defining each column's X range.
    Works for any tabular document — no bank-specific assumptions.
    """
    if not rows:
        return [(0, page_width)]

    all_boxes = [b for row in rows for b in row]
    if not all_boxes:
        return [(0, page_width)]

    # Build 1-D occupancy array
    W = min(int(page_width) + 1, 4000)
    occ = np.zeros(W, dtype=np.float32)

    for b in all_boxes:
        l = max(0, int(b["x1"]))
        r = min(W - 1, int(b["x2"]))
        if r > l:
            occ[l : r + 1] += 1.0

    # Smooth with a 6-pixel window to remove micro-gaps inside words
    kernel = np.ones(6) / 6.0
    smooth = np.convolve(occ, kernel, mode="same")

    # Find gap segments (occupancy < threshold)
    threshold = 0.05
    in_gap = False
    gap_start = 0
    separators = [0]  # always start from left edge

    for x in range(W):
        if smooth[x] < threshold:
            if not in_gap:
                in_gap = True
                gap_start = x
        else:
            if in_gap:
                in_gap = False
                gap_width = x - gap_start
                if gap_width >= min_gap:
                    # Use midpoint of the gap as the separator
                    separators.append((gap_start + x) // 2)

    if in_gap and (W - gap_start) >= min_gap:
        separators.append((gap_start + W) // 2)

    separators.append(W - 1)  # always end at right edge

    columns = [(separators[i], separators[i + 1]) for i in range(len(separators) - 1)]

    # Sanity: if we got 0 or 1 columns, fall back to single full-width column
    if len(columns) < 2:
        logger.debug("detect_columns: only %d columns found, check min_gap", len(columns))
        return [(0, page_width)]

    logger.debug("detect_columns: %d columns  separators=%s", len(columns), separators)
    return columns


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Grid Building
# Assign every box in every row to a column, merge text within each cell
# ─────────────────────────────────────────────────────────────────────────────

def build_grid(rows: list, columns: list) -> list:
    """
    Assign each box to its column (by X-center), then merge text per cell.
    Returns grid as list of rows, each row is list of cell strings.
    """
    n_cols = len(columns)
    grid = []

    for row in rows:
        cells = [""] * n_cols

        for box in row:
            cx = box["cx"]
            # Find the column this box belongs to
            col_idx = n_cols - 1  # default: last column
            for i, (x_left, x_right) in enumerate(columns):
                if x_left <= cx < x_right:
                    col_idx = i
                    break

            text = box["text"].strip()
            if cells[col_idx]:
                cells[col_idx] += " " + text
            else:
                cells[col_idx] = text

        grid.append(cells)

    return grid


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Block Detection
# Identify logical blocks: dense text regions vs sparse table regions
# ─────────────────────────────────────────────────────────────────────────────

def detect_blocks(rows: list, page_height: int = 2000) -> dict:
    """
    Split rows into:
      - header_rows: top area (informational text)
      - table_rows:  dense multi-column area (actual data grid)
      - footer_rows: bottom area

    Detection is purely geometric — no keywords.
    The table zone is where rows have the MOST boxes per row (highest column density).
    """
    if not rows:
        return {"header": [], "table": [], "footer": []}

    # Count boxes-per-row
    widths = [len(row) for row in rows]
    median_w = float(np.median(widths)) if widths else 1.0

    # A "table row" is one with >= 60% of the page's maximum boxes-per-row
    max_w = max(widths) if widths else 1
    threshold = max(2, max_w * 0.50)

    table_indices = [i for i, row in enumerate(rows) if len(row) >= threshold]

    if not table_indices:
        # Nothing looks tabular, return all as header
        return {"header": rows, "table": [], "footer": []}

    first_table = table_indices[0]
    last_table  = table_indices[-1]

    return {
        "header": rows[:first_table],
        "table":  rows[first_table : last_table + 1],
        "footer": rows[last_table + 1:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def analyze_layout(boxes: list, page_width: int = 1488, page_height: int = 2000) -> dict:
    """
    Full layout analysis on a list of normalized OCR boxes.

    Returns:
      {
        "rows":        raw grouped rows
        "blocks":      {header, table, footer} split
        "columns":     [(x_left, x_right), ...]
        "grid":        [[cell, cell, ...], ...]  (table rows only)
        "header_text": flat text of header rows (for semantic extraction)
        "n_cols":      number of detected columns
      }
    """
    rows    = detect_rows(boxes)
    blocks  = detect_blocks(rows, page_height=page_height)
    columns = detect_columns(blocks["table"] if blocks["table"] else rows,
                             page_width=page_width, min_gap=18)
    grid    = build_grid(blocks["table"], columns)

    header_text = " ".join(
        b["text"]
        for row in blocks["header"]
        for b in sorted(row, key=lambda b: (b["cy"], b["cx"]))
    )

    return {
        "rows":        rows,
        "blocks":      blocks,
        "columns":     columns,
        "grid":        grid,
        "header_text": header_text,
        "n_cols":      len(columns),
    }
