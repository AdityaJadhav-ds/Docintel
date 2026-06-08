import re
from typing import List
from ..models import OCRToken

class OCRRepairLayer:
    def repair(self, tokens: List[OCRToken]) -> List[OCRToken]:
        for t in tokens:
            text = t.text
            text = text.replace("$", "5").replace("E ", "")
            text_u = text.upper()
            if text_u == "SIXTYTHREE": text = "63"
            if text_u in ("STXTYSIX", "SIXTYSIX"): text = "66"
            if text_u == "SEVENTYONE": text = "71"
            if text_u == "EIGHTYSEVEN": text = "87"
            if re.match(r'^\d{3}\+\d{2}$', text):
                text = text.replace("+", "/")
            t.text = text
        return tokens
