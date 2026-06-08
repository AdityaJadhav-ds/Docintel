"""
academic_engine/layout_v2/spatial_relationships.py
====================================================
Geometric helpers for spatial layout analysis.

All functions operate on (x, y, w, h) bounding-box tuples or
(x1, y1, x2, y2) corner tuples — both forms are common in this codebase.

Conventions:
  BBox  = (x, y, w, h)          — top-left origin, width, height
  Rect  = (x1, y1, x2, y2)      — top-left → bottom-right corners
  Point = (x, y)
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

# Type aliases
BBox  = Tuple[int, int, int, int]    # (x, y, w, h)
Rect  = Tuple[int, int, int, int]    # (x1, y1, x2, y2)
Point = Tuple[float, float]


# ── Conversion helpers ────────────────────────────────────────────────────────

def bbox_to_rect(bbox: BBox) -> Rect:
    x, y, w, h = bbox
    return (x, y, x + w, y + h)


def rect_to_bbox(rect: Rect) -> BBox:
    x1, y1, x2, y2 = rect
    return (x1, y1, x2 - x1, y2 - y1)


def bbox_center(bbox: BBox) -> Point:
    x, y, w, h = bbox
    return (x + w / 2, y + h / 2)


def rect_center(rect: Rect) -> Point:
    x1, y1, x2, y2 = rect
    return ((x1 + x2) / 2, (y1 + y2) / 2)


def bbox_area(bbox: BBox) -> int:
    _, _, w, h = bbox
    return w * h


def rect_area(rect: Rect) -> int:
    x1, y1, x2, y2 = rect
    return max(0, x2 - x1) * max(0, y2 - y1)


# ── Distance ──────────────────────────────────────────────────────────────────

def point_distance(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def bbox_center_distance(a: BBox, b: BBox) -> float:
    return point_distance(bbox_center(a), bbox_center(b))


def vertical_distance(a: BBox, b: BBox) -> float:
    """
    Signed vertical distance between bottoms of A and top of B.
    Positive = B is below A (gap). Negative = overlap.
    """
    _, ay, _, ah = a
    _, by, _, _  = b
    return float(by - (ay + ah))


def horizontal_overlap(a: BBox, b: BBox) -> float:
    """
    Fraction of horizontal overlap between two boxes.
    1.0 = fully aligned, 0.0 = no overlap.
    """
    ax1, _, aw, _ = a
    bx1, _, bw, _ = b
    ax2 = ax1 + aw
    bx2 = bx1 + bw
    inter = max(0, min(ax2, bx2) - max(ax1, bx1))
    union = max(aw, bw)
    return inter / union if union > 0 else 0.0


# ── Containment ───────────────────────────────────────────────────────────────

def bbox_contains_point(bbox: BBox, point: Point) -> bool:
    x, y, w, h = bbox
    px, py = point
    return x <= px <= x + w and y <= py <= y + h


def bbox_contains_bbox(outer: BBox, inner: BBox) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return (ox <= ix and oy <= iy and
            ix + iw <= ox + ow and iy + ih <= oy + oh)


def rect_intersection(a: Rect, b: Rect) -> Optional[Rect]:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def iou(a: BBox, b: BBox) -> float:
    """Intersection-over-Union for two BBoxes."""
    ra = bbox_to_rect(a)
    rb = bbox_to_rect(b)
    inter = rect_intersection(ra, rb)
    if inter is None:
        return 0.0
    inter_area = rect_area(inter)
    union_area  = bbox_area(a) + bbox_area(b) - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


# ── Alignment ─────────────────────────────────────────────────────────────────

def same_row(a: BBox, b: BBox, tolerance_px: int = 15) -> bool:
    """True if two boxes are vertically close enough to be on the same line."""
    _, ay, _, ah = a
    _, by, _, bh = b
    a_mid = ay + ah / 2
    b_mid = by + bh / 2
    return abs(a_mid - b_mid) <= tolerance_px


def same_column(a: BBox, b: BBox, tolerance_px: int = 20) -> bool:
    """True if two boxes share significant horizontal overlap."""
    return horizontal_overlap(a, b) > 0.5


def is_above(a: BBox, b: BBox) -> bool:
    """True if centre of A is above centre of B."""
    return bbox_center(a)[1] < bbox_center(b)[1]


def is_right_of(a: BBox, b: BBox) -> bool:
    """True if centre of A is to the right of centre of B."""
    return bbox_center(a)[0] > bbox_center(b)[0]


# ── Grouping ──────────────────────────────────────────────────────────────────

def group_into_rows(bboxes: List[BBox], row_gap_px: int = 20) -> List[List[BBox]]:
    """
    Cluster bounding boxes into horizontal rows by vertical proximity.
    Returns list of rows, each row is a list of BBoxes sorted left→right.
    """
    if not bboxes:
        return []
    sorted_boxes = sorted(bboxes, key=lambda b: b[1])   # sort by y
    rows: List[List[BBox]] = [[sorted_boxes[0]]]

    for box in sorted_boxes[1:]:
        last_row = rows[-1]
        last_box = sorted(last_row, key=lambda b: b[1] + b[3])[-1]  # tallest
        last_bottom = last_box[1] + last_box[3]
        if box[1] <= last_bottom + row_gap_px:
            last_row.append(box)
        else:
            rows.append([box])

    # Sort each row left → right
    return [sorted(row, key=lambda b: b[0]) for row in rows]


def enclosing_bbox(bboxes: List[BBox]) -> Optional[BBox]:
    """Return the smallest BBox that encloses all given bboxes."""
    if not bboxes:
        return None
    xs = [b[0] for b in bboxes]
    ys = [b[1] for b in bboxes]
    x2s = [b[0] + b[2] for b in bboxes]
    y2s = [b[1] + b[3] for b in bboxes]
    x = min(xs); y = min(ys)
    return (x, y, max(x2s) - x, max(y2s) - y)


def sort_top_to_bottom(bboxes: List[BBox]) -> List[BBox]:
    return sorted(bboxes, key=lambda b: b[1])


def sort_left_to_right(bboxes: List[BBox]) -> List[BBox]:
    return sorted(bboxes, key=lambda b: b[0])


# ── Image-coordinate zone fractions ──────────────────────────────────────────

def fraction_crop(img_h: int, img_w: int,
                  fy0: float, fy1: float,
                  fx0: float = 0.0, fx1: float = 1.0) -> Rect:
    """
    Convert fraction-based zone description to pixel Rect.
    All fractions are 0.0–1.0 of image dimensions.
    """
    return (
        int(fx0 * img_w),
        int(fy0 * img_h),
        int(fx1 * img_w),
        int(fy1 * img_h),
    )


def clamp_rect(rect: Rect, img_h: int, img_w: int) -> Rect:
    x1, y1, x2, y2 = rect
    return (
        max(0, min(x1, img_w)),
        max(0, min(y1, img_h)),
        max(0, min(x2, img_w)),
        max(0, min(y2, img_h)),
    )
