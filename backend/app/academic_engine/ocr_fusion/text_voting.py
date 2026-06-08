from collections import defaultdict
import re

class TextVoter:
    """Intelligently votes on the best text from multiple OCR candidates."""
    
    def is_numeric_candidate(self, candidates: list) -> bool:
        # If the majority of candidates have numbers, treat as numeric
        num_count = sum(1 for c in candidates if any(char.isdigit() for char in c['text']))
        return num_count > len(candidates) / 2
        
    def vote_numeric(self, candidates: list) -> str:
        """Numeric voting. E.g. [75.17, 7517, 75.1?] -> 75.17"""
        valid_numbers = []
        for cand in candidates:
            text = cand['text']
            
            # Semantic repair
            text = text.replace('?', '7').replace('O', '0').replace('o', '0')
            text = text.replace('l', '1').replace('I', '1').replace(',', '.')
            
            # Decimal correction (if 4 digits, usually XX.XX for percentages)
            if re.match(r'^\d{4}$', text):
                text = text[:2] + '.' + text[2:]
                
            # Valid numeric format check
            if re.match(r'^\d{1,3}(\.\d{1,2})?$', text):
                valid_numbers.append((text, cand['confidence']))
                
        if not valid_numbers:
            return self.vote_text(candidates)
            
        # Confidence weighted voting among valid numbers
        counts = defaultdict(float)
        for num, conf in valid_numbers:
            counts[num] += conf
            
        return max(counts.items(), key=lambda x: x[1])[0]

    def vote_text(self, candidates: list) -> str:
        """Majority and confidence weighted voting."""
        scores = defaultdict(float)
        for cand in candidates:
            # Weighted by confidence
            # Plus small bonus if it exists in multiple engines
            scores[cand['text']] += cand['confidence'] + 0.1
            
        if not scores:
            return ""
            
        return max(scores.items(), key=lambda x: x[1])[0]
        
    def vote(self, candidates: list) -> str:
        if self.is_numeric_candidate(candidates):
            return self.vote_numeric(candidates)
        return self.vote_text(candidates)
