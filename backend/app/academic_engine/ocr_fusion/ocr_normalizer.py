import re

class OCRNormalizer:
    """Normalizes OCR output text."""
    
    def normalize(self, text: str) -> str:
        if text is None:
            text = ""
        if isinstance(text, dict):
            text = text.get("value", "")
        if isinstance(text, list):
            text = " ".join([str(v) for v in text])
        text = str(text)
        
        if not text:
            return ""
            
        # 1. Unicode corruption fixes
        text = text.replace('”', '"').replace('“', '"')
        text = text.replace('‘', "'").replace('’', "'")
        text = text.replace('—', '-').replace('–', '-')
        
        # 2. Broken spacing (PERCENTAG E -> PERCENTAGE)
        # Looks for single isolated uppercase letters next to uppercase words
        text = re.sub(r'([A-Z]{3,})\s+([A-Z])(?=[\s]|$)', r'\1\2', text)
        
        # 3. Merged words (e.g. JadhavRahul -> Jadhav Rahul)
        text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
        
        # 4. Common OCR symbol mistakes
        text = text.replace('|', 'I').replace('[', 'I').replace(']', 'I')
        
        # 5. Domain specific semantic fixes
        text = text.replace('JADHAY', 'JADHAV')
        
        return text.strip()
