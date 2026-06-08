class ConfidenceEngine:
    """Computes confidence scores for words, lines, and regions."""
    
    def compute_word_confidence(self, word_candidates: list, final_text: str) -> float:
        if not word_candidates:
            return 0.0
            
        # Find candidates that matched the final chosen text
        matching_candidates = [c for c in word_candidates if c['text'] == final_text]
        
        if not matching_candidates:
            return 0.0
            
        # Agreement ratio (how many engines agreed on this)
        agreement_ratio = len(matching_candidates) / len(word_candidates)
        
        # Average confidence of the engines that agreed
        avg_conf = sum(c['confidence'] for c in matching_candidates) / len(matching_candidates)
        
        # Final word confidence formula
        return (agreement_ratio * 0.4) + (avg_conf * 0.6)

    def compute_region_confidence(self, words: list) -> float:
        if not words:
            return 0.0
        return sum(w['confidence'] for w in words) / len(words)
