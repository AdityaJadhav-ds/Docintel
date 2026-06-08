import cv2
import numpy as np

class DebugVisualizer:
    """Visualizes fusion engine outputs for debugging."""
    
    def draw_fusion_results(self, image: np.ndarray, fused_words: list, rejected: list) -> np.ndarray:
        debug_img = image.copy()
        
        # Draw rejected candidates in red
        for r in rejected:
            x, y, w, h = r['bbox']
            cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 1)
            
        # Draw accepted final fused text in green
        for w in fused_words:
            x, y, w_box, h_box = w['bbox']
            cv2.rectangle(debug_img, (x, y), (x+w_box, y+h_box), (0, 255, 0), 2)
            cv2.putText(debug_img, f"{w['text']} ({w['confidence']:.2f})", (x, y - 5), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 0, 0), 1)
                        
        return debug_img
