import cv2
import numpy as np

def super_resolution(image: np.ndarray) -> np.ndarray:
    """Step 8: Super Resolution for low-quality photos."""
    h, w = image.shape[:2]
    # Apply only if resolution is low (e.g. < 1000px width/height)
    if max(h, w) < 1000:
        # Intelligent Upscaling using cubic interpolation
        upscaled = cv2.resize(image, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        return upscaled
    return image

def recover_blur(image: np.ndarray) -> np.ndarray:
    """Step 9: Blur Recovery (deconvolution sharpening / adaptive edge enhancement)."""
    # Adaptive sharpening using Unsharp Mask
    gaussian = cv2.GaussianBlur(image, (9, 9), 10.0)
    unsharp = cv2.addWeighted(image, 1.5, gaussian, -0.5, 0, image)
    return unsharp

def color_normalization(image: np.ndarray) -> np.ndarray:
    """Step 10: Color Normalization (Neutral OCR-friendly image)."""
    # Convert yellow/blue/pink backgrounds to white while keeping text black
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Use adaptive thresholding to find text
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 15)
    
    # Create a neutral output
    neutral = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    return neutral
