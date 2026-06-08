import re
import cv2
import numpy as np
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class SpatialNode:
    def __init__(self, text: str, x: int, y: int, w: int, h: int, conf: float):
        self.text = text
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.conf = conf
        self.center_x = x + w / 2
        self.center_y = y + h / 2

def build_spatial_graph(image: np.ndarray) -> List[SpatialNode]:
    # import pytesseract
    try:
        # Use PSM 11 (Sparse text. Find as much text as possible in no particular order)
        # or PSM 6 (Assume a single uniform block of text)
        # PSM 12 (Sparse text with OSD) is also good.
        data = pytesseract.image_to_data(image, config='--psm 11', output_type=pytesseract.Output.DICT)
        nodes = []
        n_boxes = len(data['level'])
        for i in range(n_boxes):
            text = data['text'][i].strip()
            conf = float(data['conf'][i])
            if text and conf > 10:
                x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                nodes.append(SpatialNode(text, x, y, w, h, conf))
        return nodes
    except Exception as e:
        logger.error(f"[spatial_v3] OCR extraction failed: {e}")
        return []

def extract_spatial_fields(nodes: List[SpatialNode], image_shape) -> Dict[str, Any]:
    fields = {
        "candidate_name": None,
        "percentage": None,
        "cgpa": None,
        "result": None,
        "board_university": None,
        "passing_year": None,
    }
    
    # Simple semantic anchor approach
    # Group nodes into lines approximately
    lines = []
    nodes = sorted(nodes, key=lambda n: n.y)
    current_line = []
    last_y = -1
    for n in nodes:
        if last_y == -1 or abs(n.y - last_y) < 15:
            current_line.append(n)
            last_y = (last_y * (len(current_line)-1) + n.y) / len(current_line)
        else:
            current_line.sort(key=lambda x: x.x)
            lines.append(current_line)
            current_line = [n]
            last_y = n.y
    if current_line:
        current_line.sort(key=lambda x: x.x)
        lines.append(current_line)

    from app.academic_engine.universal.academic_score_engine import extract_academic_scores
    scores = extract_academic_scores(lines)
    fields.update(scores)
    
    # Convert lines to text and map
    for i, line in enumerate(lines):
        line_text = " ".join([n.text for n in line]).upper()
        
        # 3. Result
        if re.search(r'\b(RESULT|REMARK)\b', line_text):
            search_lines = lines[i:i+3]
            for sl in search_lines:
                text_blob = " ".join([n.text for n in sl]).upper()
                if "PASS" in text_blob or "SUCCESSFUL" in text_blob:
                    fields["result"] = "PASS"
                elif "FAIL" in text_blob:
                    fields["result"] = "FAIL"
                elif "DISTINCTION" in text_blob:
                    fields["result"] = "DISTINCTION"
                elif "FIRST CLASS" in text_blob:
                    fields["result"] = "FIRST CLASS"
    
    return fields
