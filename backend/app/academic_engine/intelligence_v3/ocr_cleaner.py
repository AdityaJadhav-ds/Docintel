import re
from typing import List
from .models import OCRNode

class OCRCleaner:
    def clean(self, nodes: List[OCRNode]) -> List[OCRNode]:
        cleaned_nodes = []
        for node in nodes:
            text = node.text
            
            replacements = {
                'O': '0',
                'B': '8',
                'I': '1',
                'S': '5',
                'l': '1',
                'Z': '2',
                '|': '1',
                '{': '',
                '}': '',
                '[': '',
                ']': ''
            }
            
            # Simple heuristic for numeric text fix
            if re.match(r'^[\dOBSlZ\|]+$', text):
                for k, v in replacements.items():
                    text = text.replace(k, v)
                    
            text = re.sub(r'[^\w\s\.\-\%]', '', text)
            
            if text:
                node.text = text
                cleaned_nodes.append(node)
                
        return cleaned_nodes
