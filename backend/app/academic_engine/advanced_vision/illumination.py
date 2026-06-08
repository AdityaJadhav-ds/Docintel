import cv2
import numpy as np

def remove_glare(image: np.ndarray) -> np.ndarray:
    """Step 4: Glare / Reflection Removal using adaptive inpainting."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Detect bright reflection zones
    _, glare_mask = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY)
    
    # Expand the mask slightly to cover edges of the glare
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    glare_mask = cv2.dilate(glare_mask, kernel, iterations=2)
    
    # Inpaint to repair the overexposed areas
    repaired = cv2.inpaint(image, glare_mask, 3, cv2.INPAINT_TELEA)
    return repaired

def remove_shadows(image: np.ndarray) -> np.ndarray:
    """Step 5: Shadow Removal using illumination normalization (Retinex-like)."""
    # Convert to HSV to separate intensity
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    v_channel = hsv[:, :, 2]
    
    # Estimate background illumination using large kernel median blur
    kernel_size = min(v_channel.shape) // 10
    if kernel_size % 2 == 0:
        kernel_size += 1
    
    bg_illumination = cv2.medianBlur(v_channel, kernel_size)
    
    # Avoid division by zero
    bg_illumination = np.maximum(bg_illumination, 1)
    
    # Normalize: Target * (Image / Background)
    normalized_v = np.clip(v_channel.astype(np.float32) * 255.0 / bg_illumination, 0, 255).astype(np.uint8)
    
    hsv[:, :, 2] = normalized_v
    enhanced = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    return enhanced
