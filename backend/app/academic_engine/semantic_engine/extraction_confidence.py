class ExtractionConfidence:
    """Step 10: Confidence System"""
    
    def generate_confidence(self, candidate: dict, score: float) -> dict:
        # Normalize score to 0-1 range (heuristic)
        # Higher score means higher confidence
        normalized_conf = min(1.0, max(0.0, score / 15.0))
        
        return {
            "value": candidate['value'],
            "confidence": normalized_conf,
            "extraction_strategy": candidate['strategy'],
            "source_label": candidate['source_label'],
            "source_region": candidate['node']['bbox']
        }
