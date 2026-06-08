"""
app/fraud/image_hashing.py — Perceptual image hashing for duplicate detection
==============================================================================
Implements three complementary hash algorithms:
  - aHash (Average Hash)  — fast, good for identical images
  - dHash (Difference Hash) — good for slightly edited images
  - pHash (Perceptual Hash) — robust to resize, brightness, minor edits

Hamming distance threshold:
  0-3  → IDENTICAL
  4-10 → NEAR_DUPLICATE (resize, minor edit)
  11-20 → SIMILAR
  >20  → DIFFERENT
"""

from __future__ import annotations
import hashlib
from typing import Optional, Tuple, Dict
import numpy as np
from PIL import Image
from app.core.logger import logger


# ── Thresholds ────────────────────────────────────────────────────────────────

class HashThreshold:
    IDENTICAL      = 3
    NEAR_DUPLICATE = 10
    SIMILAR        = 20


# ── Hash computation ──────────────────────────────────────────────────────────

def _pil_to_gray(image_input) -> Image.Image:
    """Load any image input as grayscale PIL image."""
    if isinstance(image_input, Image.Image):
        return image_input.convert("L")
    if isinstance(image_input, np.ndarray):
        return Image.fromarray(image_input).convert("L")
    if hasattr(image_input, "read"):
        pos = image_input.tell()
        img = Image.open(image_input).convert("L")
        try:
            image_input.seek(pos)
        except Exception:
            pass
        return img
    return Image.open(image_input).convert("L")


def compute_ahash(image_input, hash_size: int = 8) -> str:
    """
    Average Hash: reduce to hash_size×hash_size, compare each pixel to mean.
    Returns hex string of length hash_size².
    """
    try:
        img  = _pil_to_gray(image_input).resize((hash_size, hash_size), Image.LANCZOS)
        arr  = np.array(img, dtype=np.float32)
        mean = arr.mean()
        bits = (arr > mean).flatten()
        # Pack bits into hex
        val  = int("".join("1" if b else "0" for b in bits), 2)
        return format(val, f"0{hash_size * hash_size // 4}x")
    except Exception as exc:
        logger.error("[image_hashing] ahash error: %s", exc)
        return "0" * 16


def compute_dhash(image_input, hash_size: int = 8) -> str:
    """
    Difference Hash: encode horizontal gradient (each pixel vs right neighbor).
    """
    try:
        img = _pil_to_gray(image_input).resize((hash_size + 1, hash_size), Image.LANCZOS)
        arr = np.array(img, dtype=np.float32)
        # Horizontal gradient
        diff = arr[:, 1:] > arr[:, :-1]
        bits = diff.flatten()
        val  = int("".join("1" if b else "0" for b in bits), 2)
        return format(val, f"0{hash_size * hash_size // 4}x")
    except Exception as exc:
        logger.error("[image_hashing] dhash error: %s", exc)
        return "0" * 16


def compute_phash(image_input, hash_size: int = 8, highfreq_factor: int = 4) -> str:
    """
    Perceptual Hash (DCT-based): most robust to compression, resize, brightness.
    """
    try:
        img_size = hash_size * highfreq_factor
        img  = _pil_to_gray(image_input).resize((img_size, img_size), Image.LANCZOS)
        arr  = np.array(img, dtype=np.float32)

        # DCT (2D) via row-then-column
        from scipy.fft import dct
        dct_arr = dct(dct(arr, axis=0), axis=1)

        # Take top-left hash_size × hash_size (low-frequency)
        dct_low = dct_arr[:hash_size, :hash_size]
        dct_low = dct_low.flatten()
        # Remove DC component (index 0)
        dct_low_no_dc = dct_low[1:]
        mean = dct_low_no_dc.mean()
        bits = (dct_low_no_dc > mean)
        val  = int("".join("1" if b else "0" for b in bits), 2)
        return format(val, f"0{(hash_size * hash_size - 1) // 4}x")

    except ImportError:
        # Fallback: simplified phash without scipy
        return compute_ahash(image_input, hash_size)
    except Exception as exc:
        logger.error("[image_hashing] phash error: %s", exc)
        return "0" * 16


def compute_cryptographic_hash(image_bytes: bytes) -> str:
    """SHA-256 of raw bytes — exact duplicate detection."""
    return hashlib.sha256(image_bytes).hexdigest()


def compute_all_hashes(image_input) -> Dict[str, str]:
    """Compute all three hashes. Returns {ahash, dhash, phash}."""
    return {
        "ahash": compute_ahash(image_input),
        "dhash": compute_dhash(image_input),
        "phash": compute_phash(image_input),
    }


# ── Hamming distance ──────────────────────────────────────────────────────────

def hamming_distance(hash1: str, hash2: str) -> int:
    """Bit-level Hamming distance between two hex hash strings."""
    if len(hash1) != len(hash2):
        return 999
    try:
        int1 = int(hash1, 16)
        int2 = int(hash2, 16)
        xor  = int1 ^ int2
        return bin(xor).count("1")
    except ValueError:
        return 999


def similarity_score(hash1: str, hash2: str, bits: int = 64) -> int:
    """Return 0-100 similarity from Hamming distance."""
    dist = hamming_distance(hash1, hash2)
    return max(0, int((1 - dist / bits) * 100))


def classify_hash_match(distance: int) -> str:
    """Classify the match level from Hamming distance."""
    if distance <= HashThreshold.IDENTICAL:
        return "IDENTICAL"
    if distance <= HashThreshold.NEAR_DUPLICATE:
        return "NEAR_DUPLICATE"
    if distance <= HashThreshold.SIMILAR:
        return "SIMILAR"
    return "DIFFERENT"
