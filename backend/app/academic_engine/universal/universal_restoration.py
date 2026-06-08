import cv2
import numpy as np
import logging
import re
# import pytesseract

logger = logging.getLogger(__name__)

def _find_document_contour(image: np.ndarray) -> np.ndarray:
    """Detect actual paper boundaries and ignore backgrounds/bedsheets."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 75, 200)

    # Adaptive threshold contour fusion
    adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10)
    
    # Combine Canny and Adaptive for robust edges
    combined = cv2.bitwise_or(edged, adaptive)

    # Dilation & Find contours
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dilated = cv2.dilate(combined, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None

    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            return approx
    
    # Fallback: largest contour convex hull
    largest = contours[0]
    hull = cv2.convexHull(largest)
    # Simplify hull to quadrilateral
    epsilon = 0.02 * cv2.arcLength(hull, True)
    approx = cv2.approxPolyDP(hull, epsilon, True)
    if len(approx) == 4:
        return approx

    return None

def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def _perspective_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts.reshape(4, 2))
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

def _auto_orient(image: np.ndarray) -> np.ndarray:
    try:
        # Use OSD (Orientation and Script Detection)
        osd = pytesseract.image_to_osd(image, config='--psm 0')
        search_result = re.search(r'(?<=Rotate: )\d+', osd)
        if search_result:
            angle = int(search_result.group(0))
            if angle == 90:
                return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            elif angle == 180:
                return cv2.rotate(image, cv2.ROTATE_180)
            elif angle == 270:
                return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    except Exception as e:
        logger.debug(f"OSD Orientation failed: {e}")
    return image

def _deskew(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(gray > 0)[::-1])
    angle = cv2.minAreaRect(coords)[-1]
    
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
        
    if abs(angle) < 0.5 or abs(angle) > 20:
        return image
        
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated

def normalize_document(image: np.ndarray) -> dict:
    """
    Universal normalizer that returns multiple scan variations for multi-pass OCR.
    """
    try:
        contour = _find_document_contour(image)
        if contour is not None and cv2.contourArea(contour) > 0.2 * (image.shape[0]*image.shape[1]):
            cropped = _perspective_transform(image, contour)
        else:
            cropped = image.copy()
            
        cropped = _auto_orient(cropped)
        cropped = _deskew(cropped)
            
        # Basic background cleaning
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
        
        # Adaptive Threshold (Binary)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 10
        )
        
        # High Contrast
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)
        
        # Sharpened
        kernel_sharpen = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray, -1, kernel_sharpen)
        
        return {
            "clean_scan": cropped,
            "binary_scan": binary,
            "high_contrast_scan": contrast,
            "sharpened_scan": sharpened,
        }
    except Exception as e:
        logger.error(f"[universal_restoration] Error: {e}")
        return {
            "clean_scan": image,
            "binary_scan": cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
            "high_contrast_scan": cv2.cvtColor(image, cv2.COLOR_BGR2GRAY),
            "sharpened_scan": cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        }
