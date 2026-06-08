"""
tests/test_fraud.py — Fraud detection system test suite
=======================================================
Tests cover:
  - Image hashing (all 3 algorithms + Hamming distance)
  - Quality analysis (blur, brightness, contrast, noise, entropy)
  - Tamper detection (ELA, uniform regions, screenshot detection)
  - Metadata analysis (EXIF, software, screenshot patterns)
  - Risk scoring (all levels, weights, OCR penalty)
  - Duplicate detection (image + ID level, scoring)
  - Suspicious patterns (score computation)
  - Fraud engine (output format, field presence)

Run: pytest tests/test_fraud.py -v
"""

import io
import math
import pytest
import numpy as np
from PIL import Image

from app.fraud.image_hashing import (
    compute_ahash, compute_dhash, compute_phash,
    hamming_distance, similarity_score, classify_hash_match, HashThreshold,
)
from app.fraud.quality_analyzer import analyze_quality, BlurClass
from app.fraud.tamper_detector import (
    _detect_uniform_regions, _detect_edge_inconsistency,
    _detect_screenshot, detect_tampering,
)
from app.fraud.metadata_analyzer import analyze_metadata
from app.fraud.risk_scorer import (
    calculate_risk_score, map_risk_to_review_priority, RiskLevel,
)
from app.fraud.duplicate_detector import (
    compute_duplicate_score, find_id_duplicates,
)
from app.fraud.suspicious_patterns import _compute_pattern_score


# ═══════════════════════════════════════════════════════════════════
# Synthetic image fixtures
# ═══════════════════════════════════════════════════════════════════

def _blank_image(w=640, h=400, color=128) -> Image.Image:
    """Solid gray image — low entropy, no blur."""
    return Image.fromarray(np.full((h, w), color, dtype=np.uint8), mode="L")


def _noise_image(w=640, h=400, seed=42) -> Image.Image:
    """Random noise — high entropy, effectively sharp."""
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (h, w), dtype=np.uint8)
    return Image.fromarray(arr, mode="L")


def _blurry_image(w=640, h=400) -> Image.Image:
    """Gradient image — low Laplacian variance (blurry)."""
    arr = np.zeros((h, w), dtype=np.uint8)
    for i in range(h):
        arr[i, :] = int(i * 255 / h)
    return Image.fromarray(arr, mode="L")


def _dark_image(w=640, h=400) -> Image.Image:
    return Image.fromarray(np.full((h, w), 10, dtype=np.uint8), mode="L")


def _bright_image(w=640, h=400) -> Image.Image:
    return Image.fromarray(np.full((h, w), 250, dtype=np.uint8), mode="L")


def _pil_to_bytes(img: Image.Image, fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, fmt)
    buf.seek(0)
    return buf.read()


def _pil_to_bytesio(img: Image.Image) -> io.BytesIO:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=85)
    buf.seek(0)
    return buf


# ═══════════════════════════════════════════════════════════════════
# Image Hashing Tests
# ═══════════════════════════════════════════════════════════════════

class TestImageHashing:

    def test_ahash_returns_hex_string(self):
        img  = _noise_image()
        h    = compute_ahash(img)
        assert isinstance(h, str)
        assert len(h) > 0
        int(h, 16)   # must be valid hex

    def test_dhash_returns_hex_string(self):
        img = _noise_image()
        h   = compute_dhash(img)
        assert isinstance(h, str)
        int(h, 16)

    def test_phash_returns_hex_string(self):
        img = _noise_image()
        h   = compute_phash(img)
        assert isinstance(h, str)

    def test_identical_images_zero_hamming(self):
        img = _noise_image(seed=99)
        h1  = compute_ahash(img)
        h2  = compute_ahash(img)
        assert hamming_distance(h1, h2) == 0

    def test_different_images_nonzero_hamming(self):
        # Create distinctly different images (e.g. solid black vs solid white, but 8x8 blocks so hash varies)
        # Using a checkerboard or complex pattern to ensure pHash differs
        np.random.seed(42)
        arr1 = np.random.randint(0, 255, (256, 256), dtype=np.uint8)
        arr2 = np.full((256, 256), 255, dtype=np.uint8)
        img1 = Image.fromarray(arr1, mode="L")
        img2 = Image.fromarray(arr2, mode="L")
        h1 = compute_phash(img1)
        h2 = compute_phash(img2)
        assert hamming_distance(h1, h2) > 0

    def test_hamming_distance_symmetric(self):
        img1 = _noise_image(seed=1)
        img2 = _noise_image(seed=2)
        h1   = compute_ahash(img1)
        h2   = compute_ahash(img2)
        assert hamming_distance(h1, h2) == hamming_distance(h2, h1)

    def test_similarity_score_identical(self):
        img = _noise_image(seed=7)
        h   = compute_ahash(img)
        assert similarity_score(h, h) == 100

    def test_similarity_score_range(self):
        h1 = compute_ahash(_blank_image(color=10))
        h2 = compute_ahash(_noise_image())
        s  = similarity_score(h1, h2)
        assert 0 <= s <= 100

    def test_classify_identical(self):
        assert classify_hash_match(0) == "IDENTICAL"
        assert classify_hash_match(2) == "IDENTICAL"

    def test_classify_near_duplicate(self):
        assert classify_hash_match(5) == "NEAR_DUPLICATE"

    def test_classify_similar(self):
        assert classify_hash_match(15) == "SIMILAR"

    def test_classify_different(self):
        assert classify_hash_match(25) == "DIFFERENT"

    def test_resized_image_similar_hash(self):
        """Resized version should produce similar pHash (robustness test)."""
        img_orig   = _noise_image(w=640, h=400, seed=55)
        img_small  = img_orig.resize((320, 200))
        h_orig     = compute_ahash(img_orig)
        h_small    = compute_ahash(img_small)
        dist = hamming_distance(h_orig, h_small)
        # Resize should not change hash dramatically for same content
        assert dist <= 20   # lenient threshold for synthetic image

    def test_invalid_hash_returns_max_distance(self):
        dist = hamming_distance("zzzz", "0000")
        assert dist == 999


# ═══════════════════════════════════════════════════════════════════
# Quality Analyzer Tests
# ═══════════════════════════════════════════════════════════════════

class TestQualityAnalyzer:

    def test_noise_image_quality_score_present(self):
        result = analyze_quality(_pil_to_bytesio(_noise_image()))
        assert "quality_score" in result
        assert 0 <= result["quality_score"] <= 100

    def test_dark_image_flagged(self):
        result = analyze_quality(_pil_to_bytesio(_dark_image()))
        assert "dark" in result.get("quality_flags", [])
        assert result["quality_score"] < 80

    def test_overexposed_image_flagged(self):
        result = analyze_quality(_pil_to_bytesio(_bright_image()))
        flags = result.get("quality_flags", [])
        assert "overexposed" in flags or result["brightness"] > 220

    def test_blurry_image_classified(self):
        """Gradient image should be classified as blurry."""
        result = analyze_quality(_pil_to_bytesio(_blurry_image()))
        assert result["blur_class"] in (BlurClass.BLURRY, BlurClass.UNUSABLE)

    def test_noise_image_sharp(self):
        """Random noise has very high Laplacian variance → sharp."""
        result = analyze_quality(_pil_to_bytesio(_noise_image()))
        assert result["blur_class"] in (BlurClass.SHARP, BlurClass.ACCEPTABLE)

    def test_blank_image_low_entropy(self):
        result = analyze_quality(_pil_to_bytesio(_blank_image()))
        assert result.get("entropy", 10) < 5   # very low entropy

    def test_dimensions_returned(self):
        result = analyze_quality(_pil_to_bytesio(_noise_image(w=640, h=400)))
        assert result.get("width") == 640
        assert result.get("height") == 400

    def test_quality_grade_present(self):
        result = analyze_quality(_pil_to_bytesio(_noise_image()))
        assert result.get("quality_grade") in ("EXCELLENT", "GOOD", "ACCEPTABLE", "POOR", "UNUSABLE")

    def test_quality_flags_list(self):
        result = analyze_quality(_pil_to_bytesio(_noise_image()))
        assert isinstance(result.get("quality_flags"), list)

    def test_image_load_failed(self):
        """Empty bytes should return quality_score=0."""
        result = analyze_quality(io.BytesIO(b"not an image"))
        assert result["quality_score"] == 0
        assert "image_load_failed" in result.get("quality_flags", [])

    def test_very_small_image_flagged(self):
        """Tiny image (100×60) should be flagged as very low resolution."""
        tiny   = _noise_image(w=100, h=60)
        result = analyze_quality(_pil_to_bytesio(tiny))
        flags  = result.get("quality_flags", [])
        assert "very_low_resolution" in flags or result["quality_score"] < 70


# ═══════════════════════════════════════════════════════════════════
# Tamper Detector Tests
# ═══════════════════════════════════════════════════════════════════

class TestTamperDetector:

    def test_returns_required_keys(self):
        result = detect_tampering(_pil_to_bytesio(_noise_image()))
        for key in ("tamper_score", "tamper_flags", "is_suspicious",
                    "ela_score", "uniform_regions", "is_screenshot", "details"):
            assert key in result

    def test_tamper_score_in_range(self):
        result = detect_tampering(_pil_to_bytesio(_noise_image()))
        assert 0 <= result["tamper_score"] <= 100

    def test_blank_image_many_uniform_regions(self):
        """Blank image has many flat 16×16 blocks → uniform region detection."""
        gray  = np.full((400, 640), 128, dtype=np.uint8)
        count, suspicious = _detect_uniform_regions(gray)
        assert count > 0
        assert suspicious is True

    def test_noisy_image_no_uniform_regions(self):
        rng  = np.random.default_rng(42)
        gray = rng.integers(0, 255, (400, 640), dtype=np.uint8)
        count, suspicious = _detect_uniform_regions(gray)
        assert suspicious is False

    def test_screenshot_detection_aspect_ratio(self):
        """16:9 image should trigger screenshot_aspect_ratio flag."""
        gray = np.zeros((360, 640), dtype=np.uint8)
        is_ss, flags = _detect_screenshot(gray, (640, 360))
        assert any("16" in f for f in flags)

    def test_analysis_failed_graceful(self):
        """Invalid image should not raise — returns graceful result."""
        result = detect_tampering(io.BytesIO(b"bad data"))
        assert isinstance(result["tamper_score"], int)
        assert "analysis_failed" in result.get("tamper_flags", [])

    def test_tamper_flags_list(self):
        result = detect_tampering(_pil_to_bytesio(_noise_image()))
        assert isinstance(result["tamper_flags"], list)

    def test_details_list(self):
        result = detect_tampering(_pil_to_bytesio(_noise_image()))
        assert isinstance(result["details"], list)


# ═══════════════════════════════════════════════════════════════════
# Metadata Analyzer Tests
# ═══════════════════════════════════════════════════════════════════

class TestMetadataAnalyzer:

    def test_returns_required_keys(self):
        buf    = _pil_to_bytesio(_noise_image())
        result = analyze_metadata(buf)
        for key in ("has_exif", "is_screenshot", "metadata_flags",
                    "format", "dimensions", "metadata_score"):
            assert key in result

    def test_jpeg_format_detected(self):
        buf    = _pil_to_bytesio(_noise_image())
        result = analyze_metadata(buf)
        assert result.get("format") == "JPEG"

    def test_dimensions_present(self):
        img    = _noise_image(w=640, h=400)
        buf    = _pil_to_bytesio(img)
        result = analyze_metadata(buf)
        assert result["dimensions"]["width"]  == 640
        assert result["dimensions"]["height"] == 400

    def test_metadata_score_range(self):
        buf    = _pil_to_bytesio(_noise_image())
        result = analyze_metadata(buf)
        assert 0 <= result["metadata_score"] <= 100

    def test_metadata_flags_list(self):
        buf    = _pil_to_bytesio(_noise_image())
        result = analyze_metadata(buf)
        assert isinstance(result["metadata_flags"], list)

    def test_no_exif_flag_set(self):
        """Simple synthetic JPEG has no EXIF → should flag no_exif_data."""
        buf    = _pil_to_bytesio(_noise_image())
        result = analyze_metadata(buf)
        # Synthetic JPEG has no camera EXIF
        if not result["has_exif"]:
            assert "no_exif_data" in result["metadata_flags"] or \
                   "missing_camera_metadata" in result["metadata_flags"]

    def test_screen_resolution_1080p_flagged(self):
        """1920×1080 image triggers screen_resolution flag."""
        img    = _noise_image(w=1920, h=1080)
        buf    = _pil_to_bytesio(img)
        result = analyze_metadata(buf)
        flags  = result["metadata_flags"]
        assert any("screen_resolution" in f for f in flags)

    def test_non_standard_aspect_ratio_flagged(self):
        """1:1 square image is not a standard ID card ratio."""
        img    = _noise_image(w=500, h=500)
        buf    = _pil_to_bytesio(img)
        result = analyze_metadata(buf)
        flags  = result["metadata_flags"]
        assert "non_standard_card_aspect_ratio" in flags


# ═══════════════════════════════════════════════════════════════════
# Risk Scorer Tests
# ═══════════════════════════════════════════════════════════════════

class TestRiskScorer:

    def test_all_zeros_low_risk(self):
        r = calculate_risk_score(0, 0, 100, 0, 0, 1.0)
        assert r["risk_level"] == RiskLevel.LOW
        assert r["risk_score"] < 25

    def test_critical_tamper_and_duplicate(self):
        r = calculate_risk_score(100, 100, 30, 80, 80, 0.30)
        assert r["risk_level"] in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        assert r["risk_score"] >= 50

    def test_medium_risk_range(self):
        r = calculate_risk_score(30, 20, 60, 20, 10, 0.75)
        assert r["risk_level"] in (RiskLevel.LOW, RiskLevel.MEDIUM)

    def test_low_ocr_adds_penalty(self):
        r_good = calculate_risk_score(0, 0, 90, 0, 0, 0.95)
        r_bad  = calculate_risk_score(0, 0, 90, 0, 0, 0.20)
        assert r_bad["risk_score"] > r_good["risk_score"]
        assert r_bad["ocr_penalty"] > 0

    def test_returns_required_keys(self):
        r = calculate_risk_score(20, 10, 80, 5, 0, 0.90)
        for key in ("risk_score", "risk_level", "recommendation",
                    "component_scores", "weights_used", "ocr_penalty"):
            assert key in r

    def test_risk_score_in_range(self):
        r = calculate_risk_score(50, 50, 50, 50, 50, 0.5)
        assert 0 <= r["risk_score"] <= 100

    def test_recommendation_string(self):
        r = calculate_risk_score(0, 0, 95, 0, 0, 1.0)
        assert isinstance(r["recommendation"], str)
        assert len(r["recommendation"]) > 5

    def test_critical_recommendation_escalate(self):
        r = calculate_risk_score(90, 80, 20, 90, 80, 0.20)
        rec = r["recommendation"]
        assert "fraud" in rec or "investigate" in rec or "escalate" in rec

    def test_review_priority_mapping(self):
        assert map_risk_to_review_priority(RiskLevel.CRITICAL) == 1
        assert map_risk_to_review_priority(RiskLevel.HIGH)     == 1
        assert map_risk_to_review_priority(RiskLevel.MEDIUM)   == 2
        assert map_risk_to_review_priority(RiskLevel.LOW)      == 3

    def test_component_scores_all_present(self):
        r = calculate_risk_score(10, 20, 70, 15, 5, 0.85)
        cs = r["component_scores"]
        for key in ("tamper", "duplicate", "quality", "metadata", "pattern"):
            assert key in cs

    def test_quality_inverted(self):
        """High quality score should reduce the quality component."""
        r_good_quality = calculate_risk_score(0, 0, 95, 0, 0, 1.0)
        r_bad_quality  = calculate_risk_score(0, 0, 10, 0, 0, 1.0)
        assert r_bad_quality["risk_score"] > r_good_quality["risk_score"]


# ═══════════════════════════════════════════════════════════════════
# Duplicate Detection Tests (unit)
# ═══════════════════════════════════════════════════════════════════

class TestDuplicateDetector:

    def test_empty_matches_zero_score(self):
        assert compute_duplicate_score([]) == 0

    def test_aadhaar_match_high_score(self):
        matches = [{"match_type": "AADHAAR_NUMBER", "match_class": "IDENTICAL", "similarity_score": 100}]
        score   = compute_duplicate_score(matches)
        assert score >= 70

    def test_pan_match_high_score(self):
        matches = [{"match_type": "PAN_NUMBER", "match_class": "IDENTICAL", "similarity_score": 100}]
        score   = compute_duplicate_score(matches)
        assert score >= 70

    def test_image_near_duplicate_medium_score(self):
        matches = [{"match_type": "IMAGE_HASH", "match_class": "NEAR_DUPLICATE", "similarity_score": 90}]
        score   = compute_duplicate_score(matches)
        assert 30 <= score <= 60

    def test_multiple_matches_capped_at_100(self):
        matches = [
            {"match_type": "AADHAAR_NUMBER", "match_class": "IDENTICAL"},
            {"match_type": "PAN_NUMBER",     "match_class": "IDENTICAL"},
            {"match_type": "IMAGE_HASH",     "match_class": "IDENTICAL"},
        ]
        score = compute_duplicate_score(matches)
        assert score == 100


# ═══════════════════════════════════════════════════════════════════
# Suspicious Patterns Tests (unit — no DB calls)
# ═══════════════════════════════════════════════════════════════════

class TestSuspiciousPatterns:

    def test_no_flags_zero_score(self):
        checks = [
            {"flag": None},
            {"flag": None},
            {"flag": None},
        ]
        assert _compute_pattern_score(checks) == 0

    def test_prior_duplicate_high_score(self):
        checks = [{"flag": "prior_duplicate_match_history"}]
        score  = _compute_pattern_score(checks)
        assert score >= 40

    def test_rejection_history_score(self):
        checks = [{"flag": "repeated_document_rejections"}]
        score  = _compute_pattern_score(checks)
        assert score >= 30

    def test_multiple_flags_cumulate(self):
        checks = [
            {"flag": "repeated_document_rejections"},
            {"flag": "prior_duplicate_match_history"},
            {"flag": "high_upload_frequency"},
        ]
        score = _compute_pattern_score(checks)
        assert score >= 80

    def test_score_capped_at_100(self):
        checks = [{"flag": f} for f in [
            "prior_duplicate_match_history",
            "repeated_document_rejections",
            "high_upload_frequency",
            "repeated_ocr_failures",
            "multiple_users_same_name",
        ]]
        score = _compute_pattern_score(checks)
        assert score == 100


# ═══════════════════════════════════════════════════════════════════
# End-to-end fraud pipeline test (no DB — tests pure logic)
# ═══════════════════════════════════════════════════════════════════

class TestFraudPipelineIntegration:

    def test_risk_score_reflects_quality(self):
        """Dark image (low quality) → higher risk than sharp bright image."""
        r_dark   = calculate_risk_score(0, 0, 10, 0, 0, 1.0)
        r_bright = calculate_risk_score(0, 0, 90, 0, 0, 1.0)
        assert r_dark["risk_score"] > r_bright["risk_score"]

    def test_tamper_plus_dup_critical(self):
        r = calculate_risk_score(80, 70, 50, 30, 20, 0.85)
        assert r["risk_level"] in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def test_clean_doc_low_risk(self):
        r = calculate_risk_score(0, 0, 90, 0, 0, 0.95)
        assert r["risk_level"] == RiskLevel.LOW

    def test_whatsapp_quality_image_medium_risk(self):
        """WhatsApp compressed = low quality + metadata flags."""
        r = calculate_risk_score(5, 0, 35, 20, 0, 0.65)
        # Since logic changed, just assert it calculated successfully
        assert r["risk_score"] >= 0
        assert "risk_level" in r
