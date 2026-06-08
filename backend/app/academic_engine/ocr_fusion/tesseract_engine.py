# import pytesseract
import numpy as np

class TesseractEngine:
    """Tesseract OCR Engine Implementation."""
    
    def process_region(self, image: np.ndarray, lang: str = "eng+mar", preprocess_type: str = "original") -> list:
        try:
            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
            results = []
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                if text:
                    conf = float(data['conf'][i])
                    # Tesseract sometimes returns -1 for confidence
                    if conf < 0:
                        conf = 0.0
                    results.append({
                        "text": text,
                        "confidence": conf / 100.0, # normalize to 0-1
                        "bbox": (data['left'][i], data['top'][i], data['width'][i], data['height'][i]),
                        "engine": "tesseract",
                        "preprocess_type": preprocess_type
                    })
            return results
        except Exception as e:
            return []
