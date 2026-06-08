"""
app/extraction/geometry.py
===========================
Geometry-based table reconstruction from raw PaddleOCR boxes.

Strategy:
  1. group_rows()      — Y-center proximity → rows (same line = same row)
  2. cluster_columns() — X-center clustering → column anchors
  3. assign_to_columns() — each word → nearest column anchor → structured table

NO AI. NO LLMs. NO adaptive routing.
Tables are geometry. This is how production systems work.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Types ────────────────────────────────────────────────────────────────────

# A single OCR word box as returned after flatten_paddle_result()
# {"text": str, "confidence": float, "bbox": [[x0,y0],[x1,y1],[x2,y2],[x3,y3]],
#  "cx": float, "cy": float, "x1": float, "y1": float, "x2": float, "y2": float}
Box = Dict[str, Any]
Row = List[Box]       # boxes on the same horizontal line
Table = List[Row]     # rows grouped into a table


# ── Constants ─────────────────────────────────────────────────────────────────

# Two boxes are on the same row if their Y-centers differ by less than this
# fraction of the average box height.
ROW_Y_TOLERANCE_FACTOR = 0.55

# Minimum number of rows to constitute a "transaction table"
MIN_TABLE_ROWS = 3

# If a column has at least this many entries, it's a real column (not noise)
MIN_COLUMN_FILL_RATIO = 0.20


# ── Public API ────────────────────────────────────────────────────────────────

def flatten_paddle_result(paddle_result: Any) -> List[Box]:
    """
    Convert raw PaddleOCR output to a flat list of Box dicts.
    """
    boxes: List[Box] = []
    if not paddle_result:
        return boxes

    # Handle PaddleOCR 3.5.0 / PaddleX output format
    if hasattr(paddle_result[0], "keys") or isinstance(paddle_result[0], dict):
        for res in paddle_result:
            # Safely handle dict or object access
            if hasattr(res, "get"):
                texts = res.get("rec_texts", [])
                scores = res.get("rec_scores", [])
                polys = res.get("rec_polys", [])
            else:
                texts = getattr(res, "rec_texts", [])
                scores = getattr(res, "rec_scores", [])
                polys = getattr(res, "rec_polys", [])
            
            for i in range(len(texts)):
                try:
                    text = str(texts[i]).strip()
                    if not text:
                        continue
                    conf = float(scores[i])
                    bbox = polys[i]
                    box = _make_box(bbox, text, conf)
                    if box:
                        boxes.append(box)
                except Exception as e:
                    logger.warning("[geometry] Failed to parse PaddleX box: %s", e)
        return boxes

    # Handle old PaddleOCR 2.x format
    items = paddle_result
    if items and isinstance(items[0], list) and items[0] and isinstance(items[0][0], list):
        # Already unwrapped single page — items is the line list
        pass

    for line in items:
        if line is None:
            continue
        if isinstance(line, (list, tuple)) and len(line) == 2:
            bbox, text_conf = line
            if isinstance(text_conf, (list, tuple)) and len(text_conf) == 2:
                text, conf = text_conf
            else:
                continue
            if not text or not str(text).strip():
                continue
            box = _make_box(bbox, str(text).strip(), float(conf))
            if box:
                boxes.append(box)

    if not boxes and paddle_result:
        logger.error("[geometry] PaddleOCR returned data but normalization produced 0 boxes! Raw: %s", str(paddle_result)[:500])
        raise ValueError("OCR Normalization failed: 0 boxes extracted from non-empty OCR result.")

    return boxes


def group_rows(boxes: List[Box]) -> List[Row]:
    """
    Group boxes into rows by Y-center proximity.

    Algorithm:
      - Sort boxes by Y-center (top to bottom)
      - Start a new row whenever Y-center gap > tolerance
      - Within each row, sort left-to-right by X-center

    Returns rows sorted top-to-bottom.
    """
    if not boxes:
        return []

    # Estimate typical line height from box heights
    heights = [b["y2"] - b["y1"] for b in boxes if b["y2"] > b["y1"]]
    avg_h = (sum(heights) / len(heights)) if heights else 20.0
    tolerance = avg_h * ROW_Y_TOLERANCE_FACTOR

    # Sort by Y-center
    sorted_boxes = sorted(boxes, key=lambda b: b["cy"])

    rows: List[Row] = []
    current_row: Row = [sorted_boxes[0]]
    current_cy = sorted_boxes[0]["cy"]

    for box in sorted_boxes[1:]:
        if abs(box["cy"] - current_cy) <= tolerance:
            current_row.append(box)
            # Update row center as running average
            current_cy = sum(b["cy"] for b in current_row) / len(current_row)
        else:
            rows.append(sorted(current_row, key=lambda b: b["cx"]))
            current_row = [box]
            current_cy = box["cy"]

    if current_row:
        rows.append(sorted(current_row, key=lambda b: b["cx"]))

    return rows


def cluster_columns(rows: List[Row], page_width: float = 1800.0) -> List[float]:
    """
    Find column X-anchor positions by clustering box X-centers.

    Simple approach:
      1. Collect all X-centers from all boxes
      2. Sort them
      3. Merge X-centers that are within a proximity threshold into one anchor
      4. Filter out anchors with too few boxes (noise)

    Returns sorted list of X anchor positions (left to right).
    """
    if not rows:
        return []

    # Collect all X-centers
    all_cx = []
    total_boxes = 0
    for row in rows:
        for box in row:
            all_cx.append(box["cx"])
            total_boxes += 1

    if not all_cx:
        return []

    all_cx.sort()

    # Merge nearby X-centers into clusters
    # Threshold: boxes within 5% of page width are in the same column
    merge_threshold = page_width * 0.05

    clusters: List[List[float]] = []
    current_cluster = [all_cx[0]]

    for cx in all_cx[1:]:
        if cx - current_cluster[-1] <= merge_threshold:
            current_cluster.append(cx)
        else:
            clusters.append(current_cluster)
            current_cluster = [cx]
    clusters.append(current_cluster)

    # Compute anchor = mean of cluster, filter small clusters
    anchors = []
    for cluster in clusters:
        fill_ratio = len(cluster) / max(total_boxes, 1)
        if fill_ratio >= MIN_COLUMN_FILL_RATIO:
            anchors.append(sum(cluster) / len(cluster))

    # If no anchors survived filtering, return one anchor (full-width)
    if not anchors:
        all_mean = sum(all_cx) / len(all_cx)
        anchors = [all_mean]

    return sorted(anchors)


def assign_to_columns(rows: List[Row], col_anchors: List[float]) -> List[Dict[str, Any]]:
    """
    Map each box in each row to its nearest column anchor.

    Returns a list of transaction dicts — one per row that has ≥ 2 cells.
    Each transaction has keys like "col_0", "col_1", ..., "col_N" plus "raw".

    If no column anchors, returns rows as flat text lines.
    """
    if not rows:
        return []

    if not col_anchors:
        # No column structure — return raw lines
        return [{"raw": " ".join(b["text"] for b in row), "col_0": " ".join(b["text"] for b in row)}
                for row in rows if row]

    transactions: List[Dict] = []

    for row in rows:
        if not row:
            continue

        # Build a dict: column_index → list of texts
        cell_map: Dict[int, List[str]] = {i: [] for i in range(len(col_anchors))}

        for box in row:
            # Find nearest anchor
            nearest_idx = _nearest_anchor_idx(box["cx"], col_anchors)
            cell_map[nearest_idx].append(box["text"])

        # Flatten each cell
        record: Dict[str, Any] = {}
        for col_idx, texts in cell_map.items():
            record[f"col_{col_idx}"] = " ".join(texts)

        # Raw full-row text (preserves reading order)
        record["raw"] = " ".join(b["text"] for b in row)

        # Only keep rows that have at least 1 non-empty cell
        if any(v.strip() for k, v in record.items() if k.startswith("col_")):
            transactions.append(record)

    return transactions


def extract_transactions(rows: List[Row], col_anchors: List[float]) -> List[Dict[str, Any]]:
    """
    Higher-level wrapper: attempts to detect header row and label columns.

    Returns list of labelled transaction dicts if header is detectable,
    otherwise returns raw assign_to_columns() output.
    """
    raw = assign_to_columns(rows, col_anchors)
    if len(raw) < MIN_TABLE_ROWS:
        return raw

    # Try to detect header row (first row that has text in most columns)
    header_row = raw[0]
    n_cols = len(col_anchors)
    n_filled = sum(1 for i in range(n_cols) if header_row.get(f"col_{i}", "").strip())

    if n_filled < max(2, int(n_cols * 0.5)):
        # Not a good header — return raw
        return raw

    # Use header row to rename columns
    header_labels = {
        f"col_{i}": header_row.get(f"col_{i}", f"col_{i}").strip() or f"col_{i}"
        for i in range(n_cols)
    }

    labelled = []
    for record in raw[1:]:  # skip header row
        labelled_record: Dict[str, Any] = {}
        for col_key, label in header_labels.items():
            labelled_record[label] = record.get(col_key, "")
        labelled_record["raw"] = record.get("raw", "")
        labelled.append(labelled_record)

    return labelled


# ── Internal helpers ──────────────────────────────────────────────────────────

def _make_box(bbox: Any, text: str, conf: float) -> Optional[Box]:
    """Build a normalized Box dict from a PaddleOCR bbox."""
    try:
        # bbox = [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
        pts = [[float(p[0]), float(p[1])] for p in bbox]
        x1 = min(p[0] for p in pts)
        y1 = min(p[1] for p in pts)
        x2 = max(p[0] for p in pts)
        y2 = max(p[1] for p in pts)
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        return {
            "text": text,
            "confidence": conf,
            "bbox": pts,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "cx": cx, "cy": cy,
        }
    except Exception:
        return None


def _nearest_anchor_idx(cx: float, anchors: List[float]) -> int:
    """Return index of the nearest column anchor to the given X-center."""
    return min(range(len(anchors)), key=lambda i: abs(anchors[i] - cx))
