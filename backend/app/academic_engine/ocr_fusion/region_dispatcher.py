import cv2
import numpy as np
from concurrent.futures import ThreadPoolExecutor

from .tesseract_engine import TesseractEngine
from .easyocr_engine import EasyOCREngine
from .paddleocr_engine import PaddleOCREngine

class RegionDispatcher:
    def __init__(self):
        self.tesseract = TesseractEngine()
        self.easyocr = EasyOCREngine()
        self.paddle = PaddleOCREngine()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
    def _generate_variants(self, image: np.ndarray) -> dict:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(gray, -1, kernel)
        
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)
        
        denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        
        return {
            "grayscale": gray,
            "threshold": binary,
            "sharpen": sharpened,
            "contrast": contrast,
            "denoise": denoised
        }
        
    def dispatch_region(self, region_image: np.ndarray, region_type: str, lang: str = "eng+mar") -> list:
        # Step 8: Table OCR Mode (Sparse OCR)
        if region_type == "marks_table":
            # For tables, we might only use contrast and sharpen variants to avoid breaking lines
            gray = cv2.cvtColor(region_image, cv2.COLOR_BGR2GRAY) if len(region_image.shape) == 3 else region_image
            variants = {
                "grayscale": gray,
                "sharpen": cv2.filter2D(gray, -1, np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]]))
            }
        else:
            variants = self._generate_variants(region_image)
            
        all_results = []
        
        # We can run these in parallel
        futures = []
        
        for v_name, v_img in variants.items():
            # Step 9: Language Aware OCR configuration is passed down
            futures.append(self.executor.submit(self.tesseract.process_region, v_img, lang, v_name))
            futures.append(self.executor.submit(self.easyocr.process_region, v_img, lang, v_name))
            futures.append(self.executor.submit(self.paddle.process_region, v_img, lang, v_name))
            
        for future in futures:
            res = future.result()
            if res:
                all_results.extend(res)
                
        return all_results
