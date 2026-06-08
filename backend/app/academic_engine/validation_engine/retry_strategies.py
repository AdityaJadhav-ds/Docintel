import cv2
import numpy as np

class RetryStrategies:
    """Step 5: Retry Strategies for local image crops."""
    
    @staticmethod
    def generate_variants(image: np.ndarray) -> dict:
        variants = {}
        
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        # 1. Base grayscale
        variants['grayscale'] = gray
        
        # 2. Sharpen
        kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        variants['sharpen'] = cv2.filter2D(gray, -1, kernel)
        
        # 3. Threshold (Otsu)
        _, variants['threshold'] = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        
        # 4. Denoise
        variants['denoise'] = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
        
        # 5. Enlarged (Upscaled for tiny fonts)
        variants['enlarged'] = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        
        # 6. Rotated (Slight tilt to fix skewed small crops)
        (h, w) = gray.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, 1.0, 1.0) # 1 degree
        variants['rotated'] = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
        
        return variants
