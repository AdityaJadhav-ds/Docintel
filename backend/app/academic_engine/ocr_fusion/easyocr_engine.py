import numpy as np

class EasyOCREngine:
    """EasyOCR Engine Implementation."""
    
    def __init__(self):
        self.reader_en = None
        self.reader_mr = None

    def _get_reader(self, lang: str):
        import easyocr
        if lang == "mr":
            if self.reader_mr is None:
                self.reader_mr = easyocr.Reader(['mr', 'en'], gpu=False)
            return self.reader_mr
        else:
            if self.reader_en is None:
                self.reader_en = easyocr.Reader(['en'], gpu=False)
            return self.reader_en
            
    def process_region(self, image: np.ndarray, lang: str = "en", preprocess_type: str = "original") -> list:
        try:
            reader = self._get_reader(lang)
            raw_results = reader.readtext(image)
            results = []
            for (bbox, text, prob) in raw_results:
                text = text.strip()
                if text:
                    # Convert polygon bbox to rect: (x, y, w, h)
                    xs = [pt[0] for pt in bbox]
                    ys = [pt[1] for pt in bbox]
                    x, y = int(min(xs)), int(min(ys))
                    w, h = int(max(xs) - x), int(max(ys) - y)
                    
                    results.append({
                        "text": text,
                        "confidence": float(prob),
                        "bbox": (x, y, w, h),
                        "engine": "easyocr",
                        "preprocess_type": preprocess_type
                    })
            return results
        except Exception as e:
            return []
