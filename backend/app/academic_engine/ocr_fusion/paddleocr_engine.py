import numpy as np
import threading

_GLOBAL_OCR = {}
_LOCK = threading.Lock()

class PaddleOCREngine:
    """PaddleOCR Engine Implementation."""
    
    def __init__(self):
        pass

    def _get_ocr(self, lang: str):
        global _GLOBAL_OCR, _LOCK
        from paddleocr import PaddleOCR
        
        p_lang = 'en'
        if 'mr' in lang or 'mar' in lang:
            p_lang = 'mr'
            
        with _LOCK:
            if p_lang not in _GLOBAL_OCR:
                # Disable mkldnn to avoid Windows C++ crashes with OneDNN
                _GLOBAL_OCR[p_lang] = PaddleOCR(use_angle_cls=True, lang=p_lang, enable_mkldnn=False)
            return _GLOBAL_OCR[p_lang]
            
    def process_region(self, image: np.ndarray, lang: str = "en", preprocess_type: str = "original") -> list:
        try:
            ocr = self._get_ocr(lang)
            raw_results = ocr.ocr(image, cls=True)
            results = []
            if raw_results and raw_results[0]:
                for line in raw_results[0]:
                    bbox, (text, prob) = line
                    text = text.strip()
                    if text:
                        xs = [pt[0] for pt in bbox]
                        ys = [pt[1] for pt in bbox]
                        x, y = int(min(xs)), int(min(ys))
                        w, h = int(max(xs) - x), int(max(ys) - y)
                        
                        results.append({
                            "text": text,
                            "confidence": float(prob),
                            "bbox": (x, y, w, h),
                            "engine": "paddleocr",
                            "preprocess_type": preprocess_type
                        })
            return results
        except Exception as e:
            return []
