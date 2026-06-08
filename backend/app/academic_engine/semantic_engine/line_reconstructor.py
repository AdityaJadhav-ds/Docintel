class LineReconstructor:
    """Step 1: OCR Line Reconstruction"""
    
    def reconstruct(self, words: list) -> list:
        if not words:
            return []
            
        # Sort words by y-coordinate first, then x
        sorted_words = sorted(words, key=lambda w: (w['bbox'][1], w['bbox'][0]))
        
        lines = []
        current_line = [sorted_words[0]]
        
        for word in sorted_words[1:]:
            last_word = current_line[-1]
            
            # Grouping by y-proximity and font height similarity
            y_diff = abs(word['bbox'][1] - last_word['bbox'][1])
            h_diff = abs(word['bbox'][3] - last_word['bbox'][3])
            
            # If y-difference is less than half the height of the word, it's the same line
            if y_diff < (last_word['bbox'][3] * 0.6):
                current_line.append(word)
            else:
                current_line.sort(key=lambda w: w['bbox'][0])
                lines.append(self._merge_line(current_line))
                current_line = [word]
                
        if current_line:
            current_line.sort(key=lambda w: w['bbox'][0])
            lines.append(self._merge_line(current_line))
            
        return lines
        
    def _merge_line(self, words: list) -> dict:
        x = min(w['bbox'][0] for w in words)
        y = min(w['bbox'][1] for w in words)
        w_box = max(w['bbox'][0] + w['bbox'][2] for w in words) - x
        h_box = max(w['bbox'][1] + w['bbox'][3] for w in words) - y
        
        text = " ".join(w['text'] for w in words)
        confidence = sum(w['confidence'] for w in words) / len(words)
        
        return {
            "text": text,
            "confidence": confidence,
            "bbox": (x, y, w_box, h_box),
            "words": words,
            "line_id": f"line_{id(words)}_{x}_{y}"
        }
