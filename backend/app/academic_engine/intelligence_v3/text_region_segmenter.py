import cv2
import numpy as np
from typing import List, Tuple
from .models import BBox

class TextRegionSegmenter:
    def segment(self, img: np.ndarray) -> List[Tuple[np.ndarray, BBox]]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2
        )
        
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
        dilated = cv2.dilate(thresh, kernel, iterations=2)
        
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        regions = []
        for c in contours:
            x, y, w, h = cv2.boundingRect(c)
            if w > 20 and h > 10:
                roi = img[y:y+h, x:x+w]
                bbox = BBox(x_min=x, y_min=y, x_max=x+w, y_max=y+h)
                regions.append((roi, bbox))
                
        return regions
