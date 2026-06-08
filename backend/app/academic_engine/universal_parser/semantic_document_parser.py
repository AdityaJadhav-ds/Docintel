import cv2
# import pytesseract
import numpy as np
from .relationship_graph import WordNode, DocumentGraph

def build_ocr_graph(image: np.ndarray) -> DocumentGraph:
    """Run Tesseract to get word-level bounding boxes and create a DocumentGraph."""
    # Convert to RGB if needed
    if len(image.shape) == 3 and image.shape[2] == 3:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    else:
        rgb = image
        
    data = pytesseract.image_to_data(rgb, output_type=pytesseract.Output.DICT, config='--psm 11')
    
    words = []
    word_id = 0
    for i in range(len(data['text'])):
        text = data['text'][i].strip()
        conf = float(data['conf'][i])
        
        # Tesseract returns -1 confidence for empty/block regions
        if not text or conf < 0:
            continue
            
        x = data['left'][i]
        y = data['top'][i]
        w = data['width'][i]
        h = data['height'][i]
        
        words.append(WordNode(
            id=word_id,
            text=text,
            x=x, y=y, w=w, h=h,
            conf=conf
        ))
        word_id += 1
        
    graph = DocumentGraph(words)
    graph.build_lines()
    return graph
