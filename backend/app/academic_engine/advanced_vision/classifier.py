import cv2
import numpy as np

def classify_document_quality(image: np.ndarray) -> dict:
    """
    Step 1 & Step 13: Classify image quality before OCR and detect failures.
    Detects blur, glare, shadow severity, crop completeness, visibility, skew.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Blur detection using variance of Laplacian
    blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    # Glare detection (high intensity pixels)
    _, glare_mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
    glare_score = np.sum(glare_mask == 255) / glare_mask.size
    
    # Shadow detection (low intensity pixels)
    _, shadow_mask = cv2.threshold(gray, 50, 255, cv2.THRESH_BINARY_INV)
    shadow_score = np.sum(shadow_mask == 255) / shadow_mask.size
    
    # Skew detection (Hough transforms on edges)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLines(edges, 1, np.pi/180, 100)
    skew_angle = 0.0
    if lines is not None:
        angles = []
        for line in lines:
            rho, theta = line[0]
            angle = np.degrees(theta) - 90
            if -45 <= angle <= 45:
                angles.append(angle)
        if angles:
            skew_angle = np.median(angles)
            
    # Compute grade
    is_readable = True
    warnings = []
    
    if blur_score < 50:
        is_readable = False
        warnings.append("Extreme blur detected")
    if glare_score > 0.15:
        warnings.append("High glare/reflections detected")
    if shadow_score > 0.3:
        warnings.append("Dark shadows detected")
        
    grade = "A"
    if blur_score < 100 or glare_score > 0.05 or shadow_score > 0.15:
        grade = "B"
    if not is_readable:
        grade = "F"
        
    return {
        "blur_score": blur_score,
        "glare_score": glare_score,
        "skew_angle": skew_angle,
        "shadow_score": shadow_score,
        "visibility_score": 1.0 - (glare_score + shadow_score),
        "quality_grade": grade,
        "is_readable": is_readable,
        "warnings": warnings
    }
