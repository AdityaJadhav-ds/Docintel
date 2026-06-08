"""
reading_order.py — Spatial Reading Order Engine

Sorts arbitrary bounding boxes into proper human reading order:
Top-to-bottom (Y bands), then Left-to-right (X positions).
Prevents multi-column text interleaving.
"""
import numpy as np

def sort_reading_order(boxes: list, y_tolerance_ratio: float = 0.5) -> list:
    """
    Sort boxes into Y-bands, then by X-position.
    """
    if not boxes:
        return []

    # Sort strictly by Y-center first
    sorted_y = sorted(boxes, key=lambda b: b.cy)
    
    heights = [b.height for b in sorted_y if b.height > 0]
    median_h = float(np.median(heights)) if heights else 12.0
    tol = max(4.0, median_h * y_tolerance_ratio)

    bands = []
    current_band = [sorted_y[0]]
    current_y = sorted_y[0].cy

    for b in sorted_y[1:]:
        if abs(b.cy - current_y) <= tol:
            current_band.append(b)
            # update running average Y for the band
            current_y = float(np.mean([x.cy for x in current_band]))
        else:
            bands.append(sorted(current_band, key=lambda x: x.x1))
            current_band = [b]
            current_y = b.cy

    if current_band:
        bands.append(sorted(current_band, key=lambda x: x.x1))

    ordered = []
    for band in bands:
        ordered.extend(band)

    return ordered
