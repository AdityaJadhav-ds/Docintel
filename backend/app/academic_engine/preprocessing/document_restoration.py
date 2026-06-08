"""
academic_engine/preprocessing/document_restoration.py
=======================================================
STEP 2 — Document Restoration Pipeline

12-stage preprocessing pipeline optimised for academic documents:
  1.  Orientation correction   (EXIF + content-aware)
  2.  Perspective correction   (quad detection)
  3.  Boundary detection       (document edge detection)
  4.  Crop document edges      (tight crop to document)
  5.  Background removal       (adaptive)
  6.  Shadow reduction         (rolling-ball)
  7.  WhatsApp artifact cleanup (JPEG block removal)
  8.  CLAHE contrast enhancement
  9.  Denoise                  (fastNL or bilateral)
  10. Sharpen                  (unsharp mask)
  11. Upscale 2×–4×            (Lanczos / ESRGAN stub)
  12. Deskew                   (Hough transform)

ROI-specific strategies: each extraction zone gets its own
preprocessing variant with dedicated parameters.

ISOLATION: No imports from KYC / Aadhaar / PAN modules.
"""

from __future__ import annotations
import logging
import cv2
import numpy as np
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _safe(arr: np.ndarray) -> bool:
    return arr is not None and arr.size > 0


def _to_gray(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _to_bgr(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 3 and img.shape[2] == 3:
        return img
    if len(img.shape) == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 1: Orientation correction
# ─────────────────────────────────────────────────────────────────────────────

def _correct_orientation(img: np.ndarray) -> np.ndarray:
    """Attempt tesseract OSD-based orientation fix, fallback to identity."""
    try:
        # import pytesseract
        gray = _to_gray(img)
        osd  = pytesseract.image_to_osd(gray, config="--psm 0 -c min_characters_to_try=5")
        angle_match = __import__("re").search(r"Rotate:\s*(\d+)", osd)
        if angle_match:
            angle = int(angle_match.group(1))
            if angle != 0:
                h, w = img.shape[:2]
                M = cv2.getRotationMatrix2D((w / 2, h / 2), -angle, 1.0)
                img = cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LANCZOS4,
                                     borderMode=cv2.BORDER_REPLICATE)
                logger.debug("[restoration] Orientation corrected by %d°", angle)
    except Exception:
        pass
    return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 2 + 3 + 4: Perspective correction + boundary + crop
# ─────────────────────────────────────────────────────────────────────────────

def _order_points(pts: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    s    = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def _four_point_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    widthA  = np.linalg.norm(br - bl)
    widthB  = np.linalg.norm(tr - tl)
    maxW    = max(int(widthA), int(widthB))
    heightA = np.linalg.norm(tr - br)
    heightB = np.linalg.norm(tl - bl)
    maxH    = max(int(heightA), int(heightB))
    dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]],
                   dtype="float32")
    M   = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (maxW, maxH))


def _perspective_correct(img: np.ndarray) -> np.ndarray:
    """Detect document quad and warp, with fallback to tight bounding box crop."""
    try:
        orig_h, orig_w = img.shape[:2]
        gray  = _to_gray(img)
        blur  = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blur, 50, 200)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        
        img_area = orig_h * orig_w
        if contours:
            contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
            for cnt in contours:
                peri  = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
                if len(approx) == 4:
                    pts = approx.reshape(4, 2).astype("float32")
                    area = cv2.contourArea(pts)
                    if area / img_area >= 0.25:
                        warped = _four_point_transform(img, pts)
                        logger.info("[restoration] Perspective quad applied")
                        return warped

        # Fallback: Find bounding box of the largest connected text/edge mass
        # This handles mobile photos where the quad is broken by glare or sleeves
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        fallback_contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if fallback_contours:
            largest = max(fallback_contours, key=cv2.contourArea)
            if cv2.contourArea(largest) / img_area >= 0.3:
                x, y, w, h = cv2.boundingRect(largest)
                # Add 2% padding
                pad_x, pad_y = int(orig_w * 0.02), int(orig_h * 0.02)
                x1 = max(0, x - pad_x)
                y1 = max(0, y - pad_y)
                x2 = min(orig_w, x + w + pad_x)
                y2 = min(orig_h, y + h + pad_y)
                
                # Only crop if it actually removes a significant margin
                if (x2 - x1) * (y2 - y1) < img_area * 0.95:
                    logger.info("[restoration] Fallback bounding box crop applied")
                    return img[y1:y2, x1:x2]
                    
    except Exception as exc:
        logger.debug("[restoration] Perspective correction skipped: %s", exc)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 5: Background removal (adaptive threshold mask)
# ─────────────────────────────────────────────────────────────────────────────

def _remove_background(img: np.ndarray) -> np.ndarray:
    """Light background removal — keep text, whiten non-text background."""
    try:
        gray = _to_gray(img)
        # Use large-kernel OTSU to find background threshold
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Invert so background is white
        bgr = _to_bgr(img)
        bgr[mask == 0] = [255, 255, 255]
        return bgr
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 6: Shadow reduction
# ─────────────────────────────────────────────────────────────────────────────

def _reduce_shadows(img: np.ndarray) -> np.ndarray:
    """Rolling-ball background subtraction to normalize uneven illumination."""
    try:
        gray    = _to_gray(img)
        dilated = cv2.dilate(gray, np.ones((21, 21), np.uint8))
        diff    = 255 - cv2.absdiff(gray, dilated)
        norm    = cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
        return _to_bgr(norm)
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 7: WhatsApp artifact cleanup
# ─────────────────────────────────────────────────────────────────────────────

def _cleanup_whatsapp_artifacts(img: np.ndarray) -> np.ndarray:
    """Reduce JPEG compression block artifacts common in WhatsApp photos."""
    try:
        bgr    = _to_bgr(img)
        result = cv2.fastNlMeansDenoisingColored(bgr, None, 3, 3, 7, 21)
        return result
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 8: CLAHE contrast enhancement
# ─────────────────────────────────────────────────────────────────────────────

def _apply_clahe(img: np.ndarray, clip_limit: float = 2.0, grid: int = 8) -> np.ndarray:
    """CLAHE on L-channel in LAB colour space for perceptually uniform enhancement."""
    try:
        bgr  = _to_bgr(img)
        lab  = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        L, A, B = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid, grid))
        L     = clahe.apply(L)
        lab   = cv2.merge([L, A, B])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    except Exception:
        return img


def _apply_clahe_gray(gray: np.ndarray, clip_limit: float = 3.0, grid: int = 8) -> np.ndarray:
    try:
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid, grid))
        return clahe.apply(gray)
    except Exception:
        return gray


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 9: Denoise
# ─────────────────────────────────────────────────────────────────────────────

def _denoise(img: np.ndarray, strength: int = 10) -> np.ndarray:
    try:
        bgr = _to_bgr(img)
        return cv2.fastNlMeansDenoisingColored(bgr, None, strength, strength, 7, 21)
    except Exception:
        return img


def _denoise_gray(gray: np.ndarray, strength: int = 10) -> np.ndarray:
    try:
        return cv2.fastNlMeansDenoising(gray, None, strength, 7, 21)
    except Exception:
        return gray


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 10: Sharpen
# ─────────────────────────────────────────────────────────────────────────────

_SHARPEN_KERNEL = np.array([
    [0, -1,  0],
    [-1, 5, -1],
    [0, -1,  0],
], dtype=np.float32)

_SHARPEN_STRONG_KERNEL = np.array([
    [-1, -1, -1],
    [-1,  9, -1],
    [-1, -1, -1],
], dtype=np.float32)


def _sharpen(img: np.ndarray, strong: bool = False) -> np.ndarray:
    try:
        k = _SHARPEN_STRONG_KERNEL if strong else _SHARPEN_KERNEL
        return cv2.filter2D(img, -1, k)
    except Exception:
        return img


def _unsharp_mask(img: np.ndarray, sigma: float = 1.0, amount: float = 1.5) -> np.ndarray:
    """Unsharp mask for subtle sharpening without halos."""
    try:
        blurred = cv2.GaussianBlur(img, (0, 0), sigma)
        return cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 11: Upscale
# ─────────────────────────────────────────────────────────────────────────────

def _upscale(img: np.ndarray, scale: int = 2) -> np.ndarray:
    """Lanczos upscaling. scale=2 for body text, scale=4-5 for percentage ROI."""
    if scale <= 1:
        return img
    try:
        h, w = img.shape[:2]
        return cv2.resize(img, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4)
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# STAGE 12: Deskew
# ─────────────────────────────────────────────────────────────────────────────

def _deskew(img: np.ndarray, max_angle: float = 15.0) -> np.ndarray:
    """Correct document skew using Hough line transform."""
    try:
        gray  = _to_gray(img)
        edges = cv2.Canny(gray, 50, 200, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)
        if lines is None:
            return img

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 != x1:
                angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
                angles.append(angle)

        if not angles:
            return img

        median_angle = float(np.median(angles))
        if abs(median_angle) > max_angle:
            return img

        h, w = img.shape[:2]
        M    = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
        rotated = cv2.warpAffine(img, M, (w, h),
                                  flags=cv2.INTER_LANCZOS4,
                                  borderMode=cv2.BORDER_REPLICATE)
        logger.debug("[restoration] Deskew applied: %.2f°", median_angle)
        return rotated
    except Exception:
        return img


# ─────────────────────────────────────────────────────────────────────────────
# MASTER PIPELINE — Full 12-stage restoration
# ─────────────────────────────────────────────────────────────────────────────

def _ocr_text_score(img: np.ndarray) -> int:
    """Quick Tesseract probe — returns character count as readability score."""
    try:
        # import pytesseract
        gray = _to_gray(img)
        # Downscale probe to max 800px wide for speed
        h, w = gray.shape
        if w > 800:
            gray = cv2.resize(gray, (800, int(h * 800 / w)), interpolation=cv2.INTER_AREA)
        text = pytesseract.image_to_string(gray, config="--oem 3 --psm 6", lang="eng")
        return len(text.strip())
    except Exception:
        return 0


def restore_document(img: np.ndarray, aggressive: bool = False) -> np.ndarray:
    """
    Conservative restoration pipeline with quality gate.

    CHANGED (regression fix):
      - NO full-document upscale (was causing timeout + memory issues)
      - Shadow reduction skipped if image is already bright
      - Quality gate: if restored OCR score < original, return original
      - All stages wrapped with safe fallback to previous state
    """
    if not _safe(img):
        return img

    original = img.copy()
    h, w = img.shape[:2]
    logger.info("[restoration] Input: %dx%d aggressive=%s", w, h, aggressive)

    # Stage 1: Orientation correction
    try:
        img = _correct_orientation(img)
    except Exception:
        pass

    # Stage 2-4: Perspective correction — only if image is large enough
    if h > 400 and w > 400:
        try:
            img = _perspective_correct(img)
        except Exception:
            pass

    # Stage 6: Shadow reduction — SKIP if image is already bright (avg > 180)
    # Aggressive shadow reduction on bright images destroys contrast
    try:
        gray_check = _to_gray(img)
        if float(gray_check.mean()) < 175:
            img = _reduce_shadows(img)
    except Exception:
        pass

    # Stage 7: WhatsApp artifact cleanup — light only
    try:
        img = _cleanup_whatsapp_artifacts(img)
    except Exception:
        pass

    # Stage 8: CLAHE — mild
    try:
        img = _apply_clahe(img, clip_limit=1.5 if not aggressive else 2.0)
    except Exception:
        pass

    # Stage 9: Denoise — light to avoid destroying fine characters
    try:
        img = _denoise(img, strength=7 if not aggressive else 12)
    except Exception:
        pass

    # Stage 10: Unsharp mask
    try:
        img = _unsharp_mask(img, sigma=0.8, amount=1.0)
    except Exception:
        pass

    # Stage 11: NO full-document upscale — zone-specific upscale happens in OCR step
    # (was the main cause of memory/timeout regression)

    # Stage 12: Deskew
    try:
        img = _deskew(img)
    except Exception:
        pass

    # ── Quality gate: use original if restoration made things worse ───────────
    try:
        orig_score    = _ocr_text_score(original)
        restored_score = _ocr_text_score(img)
        logger.info(
            "[restoration] OCR quality gate: original=%d restored=%d",
            orig_score, restored_score,
        )
        if restored_score < orig_score * 0.7:
            logger.warning(
                "[restoration] Restored image scored worse — using ORIGINAL"
            )
            return original
    except Exception as exc:
        logger.warning("[restoration] Quality gate error: %s", exc)

    logger.info("[restoration] Output: %dx%d", img.shape[1], img.shape[0])
    return img


# ─────────────────────────────────────────────────────────────────────────────
# ROI-SPECIFIC STRATEGIES
# ─────────────────────────────────────────────────────────────────────────────

def preprocess_header_roi(roi: np.ndarray) -> np.ndarray:
    """Zone A: Header — board name, university name, exam type."""
    if not _safe(roi):
        return roi
    roi = _apply_clahe(roi, clip_limit=2.0)
    roi = _denoise(roi, strength=8)
    roi = _unsharp_mask(roi, sigma=0.8, amount=1.2)
    roi = _upscale(roi, scale=2)
    return roi


def preprocess_candidate_roi(roi: np.ndarray) -> np.ndarray:
    """Zone B: Candidate name section."""
    if not _safe(roi):
        return roi
    roi = _reduce_shadows(roi)
    roi = _apply_clahe(roi, clip_limit=2.5)
    roi = _denoise(roi, strength=10)
    roi = _unsharp_mask(roi, sigma=1.0, amount=1.5)
    roi = _upscale(roi, scale=2)
    return roi


def preprocess_percentage_roi(roi: np.ndarray) -> np.ndarray:
    """
    Zone D: Percentage / summary area.
    7-stage intensive strategy:
      upscale 5×, grayscale, CLAHE, adaptive threshold, morph close, sharpen, deskew.
    """
    if not _safe(roi):
        return roi
    # 1. Upscale 5× first
    roi = _upscale(roi, scale=5)
    # 2. Grayscale
    gray = _to_gray(roi)
    # 3. CLAHE aggressive
    gray = _apply_clahe_gray(gray, clip_limit=4.0, grid=4)
    # 4. Denoise
    gray = _denoise_gray(gray, strength=15)
    # 5. Adaptive threshold
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 15
    )
    # 6. Morphological close to join broken digits
    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    # 7. Sharpen
    binary = _sharpen(binary, strong=True)
    return binary


def preprocess_result_roi(roi: np.ndarray) -> np.ndarray:
    """Zone D: Result / grade area — similar to percentage but less aggressive upscale."""
    if not _safe(roi):
        return roi
    roi  = _upscale(roi, scale=3)
    gray = _to_gray(roi)
    gray = _apply_clahe_gray(gray, clip_limit=3.0)
    gray = _denoise_gray(gray, strength=10)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 25, 10
    )
    return binary


def preprocess_year_roi(roi: np.ndarray) -> np.ndarray:
    """Zone A/B: Passing year — clean up date line."""
    if not _safe(roi):
        return roi
    roi  = _upscale(roi, scale=3)
    gray = _to_gray(roi)
    gray = _apply_clahe_gray(gray, clip_limit=2.0)
    return gray


def preprocess_certification_roi(roi: np.ndarray) -> np.ndarray:
    """Zone E: Certificate statement region for certificates."""
    if not _safe(roi):
        return roi
    roi = _apply_clahe(roi, clip_limit=2.0)
    roi = _denoise(roi, strength=8)
    roi = _upscale(roi, scale=2)
    return roi


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC FACTORY
# ─────────────────────────────────────────────────────────────────────────────

ROI_PREPROCESSORS = {
    "header":        preprocess_header_roi,
    "candidate":     preprocess_candidate_roi,
    "percentage":    preprocess_percentage_roi,
    "result":        preprocess_result_roi,
    "year":          preprocess_year_roi,
    "certification": preprocess_certification_roi,
}


def preprocess_for_zone(zone_name: str, roi: np.ndarray) -> np.ndarray:
    """
    Get zone-specific preprocessing for a named ROI.

    Args:
        zone_name: One of 'header' | 'candidate' | 'percentage' |
                   'result' | 'year' | 'certification'
        roi:       Cropped image numpy array.

    Returns:
        Preprocessed numpy array.
    """
    preprocessor = ROI_PREPROCESSORS.get(zone_name, preprocess_header_roi)
    return preprocessor(roi)
