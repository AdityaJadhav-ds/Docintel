from .localized_reocr import LocalizedReOCR

class RetryManager:
    """Manages the retry loop for weak fields."""
    
    def __init__(self):
        self.reocr = LocalizedReOCR()
        
    def execute_retry(self, field_data: dict, crop: object, ocr_callable) -> dict:
        candidates = self.reocr.rerun(crop, ocr_callable)
        
        if not candidates:
            return field_data
            
        # Very simple consensus voting for the retry
        # In a full system, this would call back into text_voting.py from the OCR fusion layer
        best_cand = max(candidates, key=lambda c: c['confidence'])
        
        return {
            "value": best_cand['text'],
            "confidence": best_cand['confidence'],
            "retries_used": len(candidates),
            "extraction_strategy": "localized_reocr"
        }
