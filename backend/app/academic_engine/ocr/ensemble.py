# import pytesseract
import uuid
from typing import List, Dict
import numpy as np
from ..models import OCRToken

class OCREnsemble:
    def run(self, image_variants: Dict[str, np.ndarray]) -> List[OCRToken]:
        all_tokens = []
        target_variants = ["grayscale", "adaptive"]
        configs = [("--psm 6", "tess_psm6"), ("--psm 11", "tess_psm11")]
        
        for v_name in target_variants:
            if v_name not in image_variants: continue
            img = image_variants[v_name]
            for config, eng_name in configs:
                try:
                    data = pytesseract.image_to_data(img, config=config, output_type=pytesseract.Output.DICT)
                    for i in range(len(data['text'])):
                        text = data['text'][i].strip()
                        conf = float(data['conf'][i])
                        if not text or conf < 10: continue
                        
                        x1 = data['left'][i]
                        y1 = data['top'][i]
                        x2 = x1 + data['width'][i]
                        y2 = y1 + data['height'][i]
                        
                        all_tokens.append(OCRToken(
                            text=text, confidence=conf,
                            x1=x1, y1=y1, x2=x2, y2=y2,
                            center_x=(x1+x2)/2.0, center_y=(y1+y2)/2.0,
                            engine=f"{eng_name}_{v_name}",
                            node_id=str(uuid.uuid4())
                        ))
                except Exception: pass
                
        return self._merge_tokens(all_tokens)
        
    def _merge_tokens(self, tokens: List[OCRToken]) -> List[OCRToken]:
        merged = []
        tokens_sorted = sorted(tokens, key=lambda t: t.confidence, reverse=True)
        used_boxes = []
        for t in tokens_sorted:
            overlap = False
            for b in used_boxes:
                if (t.x1 < b['x2'] and t.x2 > b['x1'] and t.y1 < b['y2'] and t.y2 > b['y1']):
                    overlap = True
                    break
            if not overlap:
                merged.append(t)
                used_boxes.append({'x1': t.x1, 'y1': t.y1, 'x2': t.x2, 'y2': t.y2})
        return merged
