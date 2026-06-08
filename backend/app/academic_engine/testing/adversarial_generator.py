"""
academic_engine/testing/adversarial_generator.py
=================================================
14 Adversarial Degradation Transforms.

Takes a clean BGR marksheet image and produces a named degraded variant.

Transforms:
  gaussian_blur       — uniform blur (σ 2–8 px)
  motion_blur         — directional motion streak
  low_brightness      — darken (simulate low-light / under-exposure)
  high_brightness     — over-expose (blown-out flash)
  perspective_skew    — 4-corner perspective warp (simulate angled photo)
  whatsapp_compress   — aggressive JPEG re-compression + chroma subsamp.
  jpeg_artifacts      — multi-round JPEG degradation
  gaussian_noise      — additive Gaussian noise
  rotation            — document rotation (1–15 degrees)
  watermark           — semi-transparent diagonal text watermark
  partial_crop        — crop 5–20% off one or two edges
  screenshot_sim      — add border chrome + slight scaling (screenshot look)
  shadow_overlay      — gradient shadow across part of image
  low_dpi             — downsample then upsample to simulate low-DPI scan

Each transform returns (degraded_bgr, metadata_dict).
"""

from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class DegradedVariant:
    name:      str             # e.g. "gaussian_blur_4.0"
    transform: str             # transform family
    image:     np.ndarray      # BGR degraded image
    params:    Dict[str, Any]  # parameters used
    severity:  float           # 0.0 (mild) – 1.0 (severe)

    def __repr__(self) -> str:
        h, w = self.image.shape[:2]
        return f"DegradedVariant({self.name!r}, {w}×{h}, severity={self.severity:.2f})"


# ── Individual transforms ─────────────────────────────────────────────────────

def _gaussian_blur(img: np.ndarray, sigma: float = 3.0) -> DegradedVariant:
    ksize = max(3, int(sigma * 2) | 1)   # must be odd
    blurred = cv2.GaussianBlur(img, (ksize, ksize), sigma)
    return DegradedVariant(
        name=f"gaussian_blur_{sigma:.1f}", transform="gaussian_blur",
        image=blurred, params={"sigma": sigma},
        severity=min(sigma / 8.0, 1.0),
    )


def _motion_blur(img: np.ndarray, length: int = 20, angle: float = 0.0) -> DegradedVariant:
    rad = math.radians(angle)
    kx  = int(round(length * math.cos(rad)))
    ky  = int(round(length * math.sin(rad)))
    size = max(abs(kx), abs(ky), 1)
    kernel = np.zeros((size * 2 + 1, size * 2 + 1), dtype=np.float32)
    cv2.line(kernel, (size - kx, size - ky), (size + kx, size + ky), 1.0, 1)
    s = kernel.sum()
    if s > 0:
        kernel /= s
    result = cv2.filter2D(img, -1, kernel)
    return DegradedVariant(
        name=f"motion_blur_L{length}_A{angle:.0f}", transform="motion_blur",
        image=result, params={"length": length, "angle": angle},
        severity=min(length / 40.0, 1.0),
    )


def _low_brightness(img: np.ndarray, factor: float = 0.45) -> DegradedVariant:
    result = np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)
    return DegradedVariant(
        name=f"low_brightness_{factor:.2f}", transform="low_brightness",
        image=result, params={"factor": factor},
        severity=1.0 - factor,
    )


def _high_brightness(img: np.ndarray, factor: float = 1.7) -> DegradedVariant:
    result = np.clip(img.astype(np.float32) * factor, 0, 255).astype(np.uint8)
    return DegradedVariant(
        name=f"high_brightness_{factor:.2f}", transform="high_brightness",
        image=result, params={"factor": factor},
        severity=min((factor - 1.0) / 1.0, 1.0),
    )


def _perspective_skew(
    img: np.ndarray,
    skew_x: float = 0.07,
    skew_y: float = 0.04,
) -> DegradedVariant:
    h, w = img.shape[:2]
    dx   = int(w * skew_x)
    dy   = int(h * skew_y)
    src  = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst  = np.float32([
        [dx, dy], [w - dx // 2, 0],
        [w, h - dy], [0, h],
    ])
    M   = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, M, (w, h),
                              borderMode=cv2.BORDER_REPLICATE)
    return DegradedVariant(
        name=f"perspective_skew_{skew_x:.2f}", transform="perspective_skew",
        image=out, params={"skew_x": skew_x, "skew_y": skew_y},
        severity=(skew_x + skew_y) / 0.3,
    )


def _whatsapp_compress(img: np.ndarray, quality: int = 40) -> DegradedVariant:
    """Simulate WhatsApp/Telegram aggressive JPEG compression."""
    # Two-pass encode/decode with chroma subsampling
    params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    _, enc = cv2.imencode(".jpg", img, params)
    dec    = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    # Second pass at slightly higher quality (WhatsApp re-encodes)
    _, enc2 = cv2.imencode(".jpg", dec, [cv2.IMWRITE_JPEG_QUALITY, quality + 15])
    final   = cv2.imdecode(enc2, cv2.IMREAD_COLOR)
    return DegradedVariant(
        name=f"whatsapp_q{quality}", transform="whatsapp_compress",
        image=final, params={"quality": quality},
        severity=1.0 - quality / 100.0,
    )


def _jpeg_artifacts(img: np.ndarray, quality: int = 20) -> DegradedVariant:
    """Extreme JPEG blocking artefacts."""
    _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    dec    = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return DegradedVariant(
        name=f"jpeg_q{quality}", transform="jpeg_artifacts",
        image=dec, params={"quality": quality},
        severity=1.0 - quality / 100.0,
    )


def _gaussian_noise(img: np.ndarray, std: float = 25.0) -> DegradedVariant:
    noise  = np.random.normal(0, std, img.shape).astype(np.float32)
    result = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return DegradedVariant(
        name=f"gaussian_noise_std{std:.0f}", transform="gaussian_noise",
        image=result, params={"std": std},
        severity=min(std / 60.0, 1.0),
    )


def _rotation(img: np.ndarray, angle: float = 5.0) -> DegradedVariant:
    h, w = img.shape[:2]
    M    = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out  = cv2.warpAffine(img, M, (w, h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
    return DegradedVariant(
        name=f"rotation_{angle:.1f}deg", transform="rotation",
        image=out, params={"angle": angle},
        severity=min(abs(angle) / 15.0, 1.0),
    )


def _watermark(img: np.ndarray, text: str = "COPY", alpha: float = 0.18) -> DegradedVariant:
    overlay = img.copy()
    h, w    = img.shape[:2]
    font    = cv2.FONT_HERSHEY_SIMPLEX
    scale   = w / 400.0
    thick   = max(2, int(scale * 3))
    tw, th  = cv2.getTextSize(text, font, scale, thick)[0]

    # Diagonal repeating pattern
    for y_off in range(-h, h * 2, int(th * 4)):
        for x_off in range(-w, w * 2, int(tw * 2)):
            cv2.putText(overlay, text, (x_off, y_off),
                        font, scale, (180, 180, 180), thick)

    result = cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0)
    return DegradedVariant(
        name=f"watermark_{alpha:.2f}", transform="watermark",
        image=result, params={"text": text, "alpha": alpha},
        severity=alpha,
    )


def _partial_crop(
    img: np.ndarray,
    edges: Tuple[float, float, float, float] = (0.0, 0.08, 0.05, 0.0),
) -> DegradedVariant:
    """Crop fractions off (top, right, bottom, left)."""
    h, w = img.shape[:2]
    top   = int(h * edges[0])
    right = int(w * edges[1])
    bot   = int(h * edges[2])
    left  = int(w * edges[3])
    cropped = img[top: h - bot if bot else h,
                  left: w - right if right else w]
    return DegradedVariant(
        name=f"partial_crop_t{edges[0]:.0%}_r{edges[1]:.0%}",
        transform="partial_crop",
        image=cropped, params={"edges": edges},
        severity=sum(edges) / 0.4,
    )


def _screenshot_sim(img: np.ndarray, border: int = 30) -> DegradedVariant:
    """Add grey browser-chrome border + slight scaling."""
    h, w   = img.shape[:2]
    scaled = cv2.resize(img, (int(w * 0.88), int(h * 0.88)), interpolation=cv2.INTER_AREA)
    sh, sw = scaled.shape[:2]
    canvas = np.full((sh + border * 2, sw + border * 2, 3), 220, dtype=np.uint8)
    canvas[border: border + sh, border: border + sw] = scaled
    return DegradedVariant(
        name="screenshot_sim", transform="screenshot_sim",
        image=canvas, params={"border": border, "scale": 0.88},
        severity=0.35,
    )


def _shadow_overlay(img: np.ndarray, direction: str = "left") -> DegradedVariant:
    h, w   = img.shape[:2]
    shadow = np.ones((h, w), dtype=np.float32)
    if direction == "left":
        for x in range(w // 2):
            shadow[:, x] = 0.35 + 0.65 * (x / (w // 2))
    elif direction == "top":
        for y in range(h // 3):
            shadow[y, :] = 0.3 + 0.7 * (y / (h // 3))
    elif direction == "diagonal":
        for i in range(min(h, w)):
            v = 0.4 + 0.6 * (i / min(h, w))
            shadow[i, :] = np.minimum(shadow[i, :], v)
            shadow[:, i] = np.minimum(shadow[:, i], v)
    shadow_3c = np.stack([shadow] * 3, axis=2)
    result    = np.clip(img.astype(np.float32) * shadow_3c, 0, 255).astype(np.uint8)
    return DegradedVariant(
        name=f"shadow_{direction}", transform="shadow_overlay",
        image=result, params={"direction": direction},
        severity=0.55,
    )


def _low_dpi(img: np.ndarray, scale: float = 0.25) -> DegradedVariant:
    """Downsample then upsample — simulates 72-DPI scan."""
    h, w    = img.shape[:2]
    small   = cv2.resize(img, (max(50, int(w * scale)), max(50, int(h * scale))),
                         interpolation=cv2.INTER_AREA)
    result  = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return DegradedVariant(
        name=f"low_dpi_scale{scale:.2f}", transform="low_dpi",
        image=result, params={"scale": scale},
        severity=1.0 - scale,
    )


# ── Transform registry ────────────────────────────────────────────────────────

_TRANSFORM_FNS = {
    "gaussian_blur":     _gaussian_blur,
    "motion_blur":       _motion_blur,
    "low_brightness":    _low_brightness,
    "high_brightness":   _high_brightness,
    "perspective_skew":  _perspective_skew,
    "whatsapp_compress": _whatsapp_compress,
    "jpeg_artifacts":    _jpeg_artifacts,
    "gaussian_noise":    _gaussian_noise,
    "rotation":          _rotation,
    "watermark":         _watermark,
    "partial_crop":      _partial_crop,
    "screenshot_sim":    _screenshot_sim,
    "shadow_overlay":    _shadow_overlay,
    "low_dpi":           _low_dpi,
}

# Default sweep parameters — multiple severities per transform
_DEFAULT_SWEEP: Dict[str, List[Dict]] = {
    "gaussian_blur":     [{"sigma": 2.0}, {"sigma": 4.0}, {"sigma": 7.0}],
    "motion_blur":       [{"length": 10, "angle": 0}, {"length": 20, "angle": 45},
                          {"length": 30, "angle": 90}],
    "low_brightness":    [{"factor": 0.6}, {"factor": 0.4}, {"factor": 0.25}],
    "high_brightness":   [{"factor": 1.4}, {"factor": 1.8}],
    "perspective_skew":  [{"skew_x": 0.05, "skew_y": 0.03},
                          {"skew_x": 0.10, "skew_y": 0.07}],
    "whatsapp_compress": [{"quality": 55}, {"quality": 35}, {"quality": 20}],
    "jpeg_artifacts":    [{"quality": 30}, {"quality": 15}],
    "gaussian_noise":    [{"std": 15.0}, {"std": 30.0}, {"std": 50.0}],
    "rotation":          [{"angle": 3.0}, {"angle": 7.0}, {"angle": 13.0}],
    "watermark":         [{"alpha": 0.12}, {"alpha": 0.30}],
    "partial_crop":      [{"edges": (0.0, 0.08, 0.0, 0.0)},
                          {"edges": (0.05, 0.0, 0.12, 0.0)},
                          {"edges": (0.05, 0.10, 0.05, 0.0)}],
    "screenshot_sim":    [{"border": 25}],
    "shadow_overlay":    [{"direction": "left"}, {"direction": "top"},
                          {"direction": "diagonal"}],
    "low_dpi":           [{"scale": 0.40}, {"scale": 0.25}, {"scale": 0.15}],
}


def generate_single(
    image: np.ndarray,
    transform: str,
    params: Optional[Dict[str, Any]] = None,
) -> DegradedVariant:
    """Apply a single named transform with explicit params."""
    fn = _TRANSFORM_FNS.get(transform)
    if fn is None:
        raise ValueError(f"Unknown transform: {transform!r}. "
                         f"Available: {sorted(_TRANSFORM_FNS)}")
    p = params or {}
    return fn(image, **p)


def generate_sweep(
    image:      np.ndarray,
    transforms: Optional[List[str]] = None,
    max_variants: int = 100,
    seed:       int  = 42,
) -> List[DegradedVariant]:
    """
    Generate a full adversarial sweep.

    Args:
        image:        Clean BGR source image.
        transforms:   Subset of transform names (None = all).
        max_variants: Cap total number of variants.
        seed:         Random seed for reproducibility.

    Returns:
        List of DegradedVariant objects.
    """
    random.seed(seed)
    np.random.seed(seed)

    families = transforms or list(_DEFAULT_SWEEP.keys())
    variants: List[DegradedVariant] = []

    for family in families:
        sweep_params = _DEFAULT_SWEEP.get(family, [{}])
        fn = _TRANSFORM_FNS.get(family)
        if fn is None:
            continue
        for params in sweep_params:
            try:
                v = fn(image.copy(), **params)
                variants.append(v)
            except Exception as exc:
                import logging
                logging.getLogger("academic_engine.testing").warning(
                    "[adversarial] %s(%s) failed: %s", family, params, exc
                )

    # Shuffle and cap
    random.shuffle(variants)
    return variants[:max_variants]


def list_transforms() -> List[str]:
    return sorted(_TRANSFORM_FNS.keys())
