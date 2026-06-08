# import pytesseract
import uuid
from typing import List, Tuple
import numpy as np
from .models import OCRNode, BBox

class OCREnsembleEngine:
    def run_ensemble(self, img: np.ndarray, regions: List[Tuple[np.ndarray, BBox]]) -> List[OCRNode]:
        nodes = []
        
        for roi, bbox in regions:
            config = "--psm 6"
            
            try:
                data = pytesseract.image_to_data(roi, config=config, output_type=pytesseract.Output.DICT)
            except Exception:
                continue
                
            for i in range(len(data['text'])):
                text = data['text'][i].strip()
                if not text:
                    continue
                    
                conf = float(data['conf'][i])
                if conf < 10:
                    continue
                    
                lx = data['left'][i]
                ly = data['top'][i]
                lw = data['width'][i]
                lh = data['height'][i]
                
                gx_min = bbox.x_min + lx
                gy_min = bbox.y_min + ly
                gx_max = gx_min + lw
                gy_max = gy_min + lh
                
                node = OCRNode(
                    text=text,
                    confidence=conf,
                    bbox=BBox(x_min=gx_min, y_min=gy_min, x_max=gx_max, y_max=gy_max),
                    engine="tesseract_psm6",
                    node_id=str(uuid.uuid4())
                )
                nodes.append(node)
                
        return nodes
