import cv2
import numpy as np

def ocr_readiness_optimizer(variants: dict) -> str:
    """Step 12: OCR Readiness Optimizer."""
    best_variant = None
    best_score = -1
    
    for name, img in variants.items():
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
            
        # Measure contrast
        contrast = gray.std()
        
        # Measure text sharpness
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        
        # Measure edge quality
        edges = cv2.Canny(gray, 100, 200)
        edge_quality = np.sum(edges == 255) / edges.size
        
        score = contrast * 0.4 + sharpness * 0.4 + edge_quality * 0.2
        
        if score > best_score:
            best_score = score
            best_variant = name
            
    return best_variant
