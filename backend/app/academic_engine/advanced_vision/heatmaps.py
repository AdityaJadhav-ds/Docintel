import cv2
import numpy as np

def generate_debug_heatmaps(image: np.ndarray, regions: list, contours: np.ndarray, shadow_mask: np.ndarray) -> dict:
    """Step 14: Debug Heatmaps."""
    heatmaps = {}
    
    # Text regions heatmap
    text_heatmap = image.copy()
    for (x, y, w, h) in regions:
        cv2.rectangle(text_heatmap, (x, y), (x+w, y+h), (0, 255, 0), 2)
    heatmaps["text_regions"] = text_heatmap
    
    # Contours heatmap
    contour_heatmap = image.copy()
    if contours is not None:
        cv2.drawContours(contour_heatmap, [contours], -1, (0, 0, 255), 3)
    heatmaps["contours"] = contour_heatmap
    
    # Shadows heatmap
    if shadow_mask is not None and shadow_mask.shape == image.shape[:2]:
        shadow_colored = cv2.applyColorMap(shadow_mask, cv2.COLORMAP_JET)
        heatmaps["shadow_map"] = cv2.addWeighted(image, 0.6, shadow_colored, 0.4, 0)
        
    return heatmaps
