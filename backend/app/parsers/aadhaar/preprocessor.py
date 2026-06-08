"""
app/parsers/aadhaar/preprocessor.py — Aadhaar-optimised image preprocessing
===========================================================================
Applies a chain of OpenCV transforms specifically tuned for Aadhaar cards:
  1. Orientation correction  (exif + face-based rotation)
  2. Perspective/skew correction
  3. Brightness & contrast normalisation (CLAHE)
  4. Denoising
  5. Sharpening
  6. Adaptive threshold binarisation
  7. Upscaling for small images

Returns a set of preprocessed variants for multi-pass OCR voting.
"""

from __future__ import annotations

import cv2
import numpy as np
from typing import Dict, Optional, Tuple
from app.core.logger import logger


# ─────────────────────────────────────────────────────────────────────────────
# 1. ORIENTATION CORRECTION
# ─────────────────────────────────────────────────────────────────────────────

def _correct_orientation(img: np.ndarray) -> np.ndarray:
    """
    Attempt to correct card orientation using face detection.
    If no face is found in the original orientation, try rotating 90 / 180 / 270
    and keep the rotation that successfully detects a face.
    Falls back to EXIF-free heuristic (landscape vs portrait aspect ratio).
    """
    try:
        face_cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(face_cascade_path)
        if face_cascade.empty():
            raise RuntimeError("cascade not loaded")

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        def detect(arr):
            return len(face_cascade.detectMultiScale(
                arr, scaleFactor=1.1, minNeighbors=4, minSize=(20, 20)
            )) > 0

        if detect(gray):
            return img  # already correct

        for angle in (90, 270, 180):
            rotated_full = _rotate(img, angle)
            rotated_gray = cv2.cvtColor(rotated_full, cv2.COLOR_BGR2GRAY) if len(rotated_full.shape) == 3 else rotated_full
            if detect(rotated_gray):
                logger.info("[aadhaar_preproc] Orientation corrected by %d°", angle)
                return rotated_full
    except Exception as e:
        logger.debug("[aadhaar_preproc] Face-based orientation failed: %s", e)

    # Fallback: Aadhaar cards are usually landscape — if portrait, rotate 90
    h, w = img.shape[:2]
    if h > w * 1.2:
        logger.debug("[aadhaar_preproc] Portrait→Landscape rotation applied")
        return _rotate(img, 90)
    return img


def _rotate(img: np.ndarray, angle: int) -> np.ndarray:
    """Rotate image by 90/180/270 degrees without cropping."""
    if angle == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if angle == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    if angle == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


# ─────────────────────────────────────────────────────────────────────────────
# 2. SKEW CORRECTION
# ─────────────────────────────────────────────────────────────────────────────

def _correct_skew(gray: np.ndarray) -> np.ndarray:
    """
    Detect and correct slight rotation (skew) using Hough line transforms.
    Only corrects if skew angle is between 0.5° and 15°.
    """
    try:
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        edges = cv2.Canny(binary, 50, 150, apertureSize=3)
        lines = cv2.HoughLines(edges, 1, np.pi / 180, threshold=100)
        if lines is None:
            return gray

        angles = []
        for line in lines[:20]:
            rho, theta = line[0]
            angle = np.degrees(theta) - 90
            if -15 < angle < 15:
                angles.append(angle)

        if not angles:
            return gray

        median_angle = float(np.median(angles))
        if abs(median_angle) < 0.5:
            return gray

        h, w = gray.shape
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
        corrected = cv2.warpAffine(gray, M, (w, h),
                                   flags=cv2.INTER_LINEAR,
                                   borderMode=cv2.BORDER_REPLICATE)
        logger.debug("[aadhaar_preproc] Skew corrected: %.2f°", median_angle)
        return corrected
    except Exception as e:
        logger.debug("[aadhaar_preproc] Skew correction failed: %s", e)
        return gray


# ─────────────────────────────────────────────────────────────────────────────
# 3 – 7. PER-PIXEL IMAGE ENHANCEMENT CHAIN
# ─────────────────────────────────────────────────────────────────────────────

def _to_gray(img: np.ndarray) -> np.ndarray:
    if len(img.shape) == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img.copy()


def _ensure_min_size(gray: np.ndarray, min_h: int = 600) -> np.ndarray:
    """Upscale if the image is too small for reliable OCR."""
    h, w = gray.shape[:2]
    if h < min_h:
        scale = min_h / h
        new_w, new_h = int(w * scale), int(h * scale)
        gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        logger.debug("[aadhaar_preproc] Upscaled to %dx%d", new_w, new_h)
    return gray


def _apply_clahe(gray: np.ndarray, clip: float = 3.0) -> np.ndarray:
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8))
    return clahe.apply(gray)


def _denoise(gray: np.ndarray) -> np.ndarray:
    return cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)


def _sharpen(gray: np.ndarray, strength: float = 1.5) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (0, 0), 1.5)
    return cv2.addWeighted(gray, strength, blurred, -(strength - 1), 0)


def _adaptive_thresh(gray: np.ndarray) -> np.ndarray:
    return cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=21,
        C=10,
    )


def _otsu_thresh(gray: np.ndarray) -> np.ndarray:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def preprocess_aadhaar(
    img: np.ndarray,
    correct_orientation: bool = True,
) -> Dict[str, np.ndarray]:
    """
    Full Aadhaar preprocessing pipeline.

    Returns a dict of named variants:
      - "base"      : denoised + CLAHE + sharpen (for region OCR)
      - "thresh"    : adaptive threshold (high contrast text)
      - "otsu"      : Otsu binarised (alternative text extraction)
      - "clahe_only": CLAHE-only (preserve gray gradients)
      - "original"  : just to-gray + upscale

    All variants are grayscale uint8 numpy arrays.
    """
    # Step 1: orientation
    if correct_orientation:
        img = _correct_orientation(img)

    gray = _to_gray(img)
    gray = _ensure_min_size(gray)

    # Step 2: skew
    gray = _correct_skew(gray)

    # Build variants
    original = gray.copy()

    clahe_only = _apply_clahe(gray, clip=3.0)
    denoised   = _denoise(clahe_only)
    base       = _sharpen(denoised, strength=1.5)
    thresh     = _adaptive_thresh(base)
    otsu       = _otsu_thresh(base)
    strong_clahe = _apply_clahe(gray, clip=5.0)

    variants = {
        "original":   original,
        "clahe_only": clahe_only,
        "base":       base,
        "thresh":     thresh,
        "otsu":       otsu,
        "strong":     _sharpen(strong_clahe, strength=2.0),
    }

    logger.debug("[aadhaar_preproc] Preprocessing done — %d variants, size=%s",
                 len(variants), gray.shape)
    return variants
