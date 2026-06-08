import cv2
import numpy as np

def detect_text_regions(image: np.ndarray) -> list:
    """Step 6: Text Region Detection using morphological maps."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Morphological gradient to enhance edges of text
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, kernel)
    
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    
    # Connect horizontally
    connected = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (20, 5)))
    
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    regions = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 15 and h > 8:
            regions.append((x, y, w, h))
            
    return regions

def preserve_tables(image: np.ndarray) -> dict:
    """Step 7: Table Structure Preservation."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Detect horizontal lines
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    horizontal = cv2.morphologyEx(gray, cv2.MORPH_OPEN, horiz_kernel, iterations=2)
    
    # Detect vertical lines
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    vertical = cv2.morphologyEx(gray, cv2.MORPH_OPEN, vert_kernel, iterations=2)
    
    # Combine lines to form structure mask
    structure_mask = cv2.add(horizontal, vertical)
    
    # Remove lines from image for OCR
    ocr_image = cv2.add(gray, structure_mask)
    
    return {
        "ocr_image": cv2.cvtColor(ocr_image, cv2.COLOR_GRAY2BGR),
        "table_image": image,
        "structure_mask": structure_mask
    }

def multi_ocr_zone_strategy(image: np.ndarray, regions: list) -> dict:
    """Step 11: Multi-OCR Zone Strategy. Groups text regions into Header, Body, Footer."""
    h, w = image.shape[:2]
    
    zones = {
        "header": [],
        "student_info": [],
        "marks_table": [],
        "footer": [],
        "signatures": []
    }
    
    for (rx, ry, rw, rh) in regions:
        # Simple heuristic based on vertical position
        if ry < h * 0.2:
            zones["header"].append((rx, ry, rw, rh))
        elif ry < h * 0.4:
            zones["student_info"].append((rx, ry, rw, rh))
        elif ry < h * 0.8:
            zones["marks_table"].append((rx, ry, rw, rh))
        else:
            if rw > w * 0.4:
                zones["footer"].append((rx, ry, rw, rh))
            else:
                zones["signatures"].append((rx, ry, rw, rh))
                
    return zones
