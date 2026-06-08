"""
table_engine.py — Phrase-Based Table Grid Engine v2

KEY RULES:
  1. Input is PHRASE-MERGED lines — not raw word boxes.
  2. Column anchors are computed from PHRASE centers, not word centers.
  3. Clustering tolerance = 45px (not 5-10px).
  4. Require ≥ 2 lines to agree on each column before accepting it.
  5. Multiline cell support: detect continuation rows and append to previous.
  6. raw_lines always preserved for fallback.
  7. Never force a grid if the result is wider than expected.

PIPELINE POSITION:
  region_engine (detects table region)
    → table_engine (builds stable grid from phrases)
"""
import re
import numpy as np
import logging
from layout_tree import Region, Line, Word

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Patterns for continuation row detection
# ─────────────────────────────────────────────────────────────────────────────

# A "date-like" pattern: 01, 02 Feb, 2026-01-01, etc.
_DATE_RE = re.compile(
    r'\b(\d{1,2}[-/\s]?\w{3}|\d{4}[-/]\d{2}[-/]\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b',
    re.IGNORECASE
)
# An "amount-like" pattern: digits optionally with commas/dots
_AMOUNT_RE = re.compile(r'\b\d[\d,]*\.?\d*\b')


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def process_table_region(table_region: Region) -> dict:
    """
    Build a stable grid from a table region whose lines contain phrase tokens.

    Returns and stores in table_region.content:
    {
        "anchors":    [float, ...],       # column x-center positions
        "grid":       [[str, ...], ...],  # final merged grid
        "raw_lines":  [str, ...],         # always present for fallback
        "n_cols":     int,
        "n_rows":     int,
    }
    """
    raw_lines = [l.text for l in table_region.lines]

    if not table_region.lines:
        result = {"anchors": [], "grid": [], "raw_lines": raw_lines, "n_cols": 0, "n_rows": 0}
        table_region.content = result
        return result

    # ── 1. Collect phrase centers ───────────────────────────────────────────
    all_cx = []
    for line in table_region.lines:
        for phrase in line.words:   # words are now phrase tokens
            all_cx.append(phrase.cx)

    if not all_cx:
        result = {"anchors": [], "grid": [], "raw_lines": raw_lines, "n_cols": 0, "n_rows": 0}
        table_region.content = result
        return result

    # ── 2. Stable column clustering (45px tolerance) ────────────────────────
    anchors = _cluster_anchors(all_cx, tol=45.0)

    # ── 3. Require each column to be confirmed by ≥ 2 rows ──────────────────
    anchors = _filter_sparse_anchors(anchors, table_region.lines, min_rows=2)

    if not anchors:
        # Fallback: single-column raw text
        result = {
            "anchors": [],
            "grid": [[l.text] for l in table_region.lines],
            "raw_lines": raw_lines,
            "n_cols": 1,
            "n_rows": len(table_region.lines),
        }
        table_region.content = result
        return result

    logger.debug(
        "table_engine: %d phrase anchors → %s", len(anchors), [round(a) for a in anchors]
    )

    # ── 4. Snap phrases to grid ─────────────────────────────────────────────
    raw_grid = _build_raw_grid(table_region.lines, anchors)

    # ── 5. Multiline cell merging ────────────────────────────────────────────
    grid = _merge_continuation_rows(raw_grid, anchors)

    # ── 6. Safety valve: if grid is absurdly wide, use raw fallback ──────────
    if len(anchors) > 12:
        logger.warning(
            "table_engine: %d anchors detected — too many, falling back to raw lines",
            len(anchors)
        )
        result = {
            "anchors": [],
            "grid": [[l.text] for l in table_region.lines],
            "raw_lines": raw_lines,
            "n_cols": 1,
            "n_rows": len(table_region.lines),
            "fallback": True,
        }
        table_region.content = result
        return result

    result = {
        "anchors":   anchors,
        "grid":      grid,
        "raw_lines": raw_lines,
        "n_cols":    len(anchors),
        "n_rows":    len(grid),
    }
    table_region.content = result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Column Clustering
# ─────────────────────────────────────────────────────────────────────────────

def _cluster_anchors(cx_values: list, tol: float = 45.0) -> list:
    """
    1D cluster of X-centers with given tolerance.
    Returns sorted list of cluster mean positions.
    """
    if not cx_values:
        return []

    sorted_cx = sorted(cx_values)
    clusters = [[sorted_cx[0]]]

    for x in sorted_cx[1:]:
        if x - float(np.mean(clusters[-1])) <= tol:
            clusters[-1].append(x)
        else:
            clusters.append([x])

    return sorted([float(np.mean(c)) for c in clusters])


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Filter sparse anchors
# ─────────────────────────────────────────────────────────────────────────────

def _filter_sparse_anchors(anchors: list, lines: list, min_rows: int = 2) -> list:
    """
    Remove column anchors that appear in fewer than min_rows lines.
    This prevents single-word outliers from creating ghost columns.
    """
    if not anchors or not lines:
        return anchors

    anchor_hits = [0] * len(anchors)

    for line in lines:
        seen_in_line = set()
        for phrase in line.words:
            idx = _nearest_anchor_idx(phrase.cx, anchors)
            seen_in_line.add(idx)
        for idx in seen_in_line:
            anchor_hits[idx] += 1

    valid = [a for a, hits in zip(anchors, anchor_hits) if hits >= min_rows]
    removed = len(anchors) - len(valid)
    if removed:
        logger.debug("_filter_sparse_anchors: removed %d ghost columns", removed)
    return valid


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — Build raw grid
# ─────────────────────────────────────────────────────────────────────────────

def _build_raw_grid(lines: list, anchors: list) -> list:
    """
    Snap each phrase to its nearest anchor column.
    Returns list-of-rows, each row is a list of cell strings.
    """
    grid = []
    for line in lines:
        cells = [""] * len(anchors)
        for phrase in line.words:
            idx = _nearest_anchor_idx(phrase.cx, anchors)
            existing = cells[idx]
            cells[idx] = (existing + " " + phrase.text).strip() if existing else phrase.text
        grid.append(cells)
    return grid


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Multiline cell merging
# ─────────────────────────────────────────────────────────────────────────────

def _merge_continuation_rows(grid: list, anchors: list) -> list:
    """
    Detect continuation rows and append their text to the previous row.

    A row is a continuation if:
      - It has only 1 or 2 non-empty cells
      - Its first non-empty cell does NOT contain a date-like or amount-like token
      - It aligns with a "description" column (not the first column)
      - The previous row has a date/amount column populated

    When found → append to the matching cell of the previous row.
    """
    if not grid:
        return grid

    merged = [grid[0][:]]   # deep copy first row

    for row in grid[1:]:
        non_empty = [(i, cell) for i, cell in enumerate(row) if cell.strip()]

        if _is_continuation(row, merged[-1]):
            # Append to previous row's non-empty description cells
            prev = merged[-1]
            for i, cell in non_empty:
                prev[i] = (prev[i] + " " + cell).strip() if prev[i] else cell
        else:
            merged.append(row[:])

    return merged


def _is_continuation(row: list, prev_row: list) -> bool:
    """
    Returns True if `row` is a continuation of `prev_row`.
    """
    non_empty = [cell for cell in row if cell.strip()]

    # A full row is never a continuation
    if len(non_empty) >= len(row) * 0.65:
        return False

    # If nothing is non-empty, skip
    if not non_empty:
        return False

    # Check if any non-empty cell looks like a date or amount
    all_text = " ".join(non_empty)
    if _DATE_RE.search(all_text):
        return False
    if _AMOUNT_RE.search(all_text) and len(non_empty) >= 2:
        return False

    # Must have a previous row with some real content
    prev_non_empty = [cell for cell in prev_row if cell.strip()]
    if len(prev_non_empty) < 2:
        return False

    return True


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _nearest_anchor_idx(cx: float, anchors: list) -> int:
    """Return the index of the nearest anchor to cx."""
    best_idx = 0
    best_dist = float("inf")
    for i, anchor in enumerate(anchors):
        d = abs(cx - anchor)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx
