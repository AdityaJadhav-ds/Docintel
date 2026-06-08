from .retry_strategies import RetryStrategies

class LocalizedReOCR:
    """Step 4: Localized Re-OCR
    Instead of full document OCR, this dynamically requests OCR strictly on weak bounding boxes.
    """
    def __init__(self):
        # We would inject OCR engines here (Tesseract, EasyOCR). 
        # For architecture separation, we assume a mock/interface.
        pass
        
    def rerun(self, crop: object, ocr_callable) -> list:
        if crop is None:
            return []
            
        variants = RetryStrategies.generate_variants(crop)
        
        all_candidates = []
        for name, img in variants.items():
            # Pass each variant to the external OCR callable injected by the pipeline
            results = ocr_callable(img, variant_name=name)
            all_candidates.extend(results)
            
        return all_candidates
