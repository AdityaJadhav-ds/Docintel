import cv2
import numpy as np

def multi_contour_detection(image: np.ndarray) -> np.ndarray:
    """Step 2: Detect ALL document-like contours and pick the best one."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(edges, kernel, iterations=2)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    best_contour = None
    best_score = -1
    
    img_area = image.shape[0] * image.shape[1]
    
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.05 * img_area:
            continue
            
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        
        if len(approx) == 4:
            # Score based on rectangularity and area
            x, y, w, h = cv2.boundingRect(approx)
            aspect_ratio = float(w)/h
            rect_area = w * h
            rectangularity = area / rect_area if rect_area > 0 else 0
            
            score = (area / img_area) * rectangularity
            
            # Penalize extreme aspect ratios
            if aspect_ratio > 3 or aspect_ratio < 0.33:
                score *= 0.5
                
            if score > best_score:
                best_score = score
                best_contour = approx
                
    if best_contour is None and contours:
        # Fallback to largest
        largest = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(largest)
        peri = cv2.arcLength(hull, True)
        best_contour = cv2.approxPolyDP(hull, 0.02 * peri, True)
        
    return best_contour

def order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def curved_page_flattening(image: np.ndarray, contour: np.ndarray) -> np.ndarray:
    """Step 3: Curved Page Flattening."""
    if contour is None or len(contour) != 4:
        return image
        
    rect = order_points(contour.reshape(4, 2))
    (tl, tr, br, bl) = rect

    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    
    return warped
