import cv2
import numpy as np

class InputNormalizer:
    def normalize(self, image_bytes: bytes) -> np.ndarray:
        np_arr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Corrupted image or invalid format.")
        
        # 1. Image validation
        if img.shape[0] < 100 or img.shape[1] < 100:
            raise ValueError("Image too small to be a document.")
            
        # 3. Resolution normalization (target ~ 2000px largest dimension for OCR)
        max_dim = max(img.shape[0], img.shape[1])
        if max_dim > 3000:
            scale = 3000 / max_dim
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        elif max_dim < 1500:
            scale = 1500 / max_dim
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            
        # 4. Color normalization
        # Convert to standard colorspace, though cv2 loads as BGR. We stick with BGR.
        return img
