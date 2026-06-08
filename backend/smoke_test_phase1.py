"""
Phase 1 smoke test — validates all 6 core engines work correctly.
Run from backend/ with: venv\Scripts\python.exe smoke_test_phase1.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import traceback

PASS = []
FAIL = []

def test(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [PASS] {name}")
    except Exception as e:
        FAIL.append((name, str(e)))
        print(f"  [FAIL] {name}: {e}")
        traceback.print_exc()

# ── 1. filter_garbage_words ────────────────────────────────────────────────────
def test_garbage_filter():
    from app.extraction.line_builder import filter_garbage_words
    words = [
        {"text": "Account", "x1": 10, "y1": 20, "x2": 80, "y2": 38, "confidence": 0.95},
        {"text": "No:", "x1": 85, "y1": 21, "x2": 110, "y2": 38, "confidence": 0.92},
        {"text": "!!!BAD!!!", "x1": 5, "y1": 90, "x2": 60, "y2": 105, "confidence": 0.10},
        {"text": "|", "x1": 5, "y1": 100, "x2": 10, "y2": 115, "confidence": 0.90},
    ]
    clean = filter_garbage_words(words)
    assert len(clean) == 2, f"expected 2 clean words, got {len(clean)}"

test("filter_garbage_words", test_garbage_filter)

# ── 2. build_lines ─────────────────────────────────────────────────────────────
def test_build_lines():
    from app.extraction.line_builder import filter_garbage_words, build_lines
    words = [
        {"text": "Account", "x1": 10, "y1": 20, "x2": 80, "y2": 38, "confidence": 0.95},
        {"text": "No:", "x1": 85, "y1": 21, "x2": 110, "y2": 38, "confidence": 0.92},
        {"text": "123456789", "x1": 115, "y1": 22, "x2": 230, "y2": 38, "confidence": 0.98},
        {"text": "Balance", "x1": 10, "y1": 55, "x2": 80, "y2": 72, "confidence": 0.91},
        {"text": "5000.00", "x1": 85, "y1": 55, "x2": 150, "y2": 72, "confidence": 0.88},
    ]
    clean = filter_garbage_words(words)
    lines = build_lines(clean)
    assert len(lines) == 2, f"expected 2 lines, got {len(lines)}"
    assert "Account" in lines[0]["text"], f"line 0 should contain Account: {lines[0]}"
    assert "Balance" in lines[1]["text"], f"line 1 should contain Balance: {lines[1]}"
    assert isinstance(lines[0]["is_bold"], bool)
    assert isinstance(lines[0]["indent_level"], int)
    print(f"    Lines: {[l['text'] for l in lines]}")

test("build_lines", test_build_lines)

# ── 3. analyze_geometry ────────────────────────────────────────────────────────
def test_geometry():
    from app.extraction.geometry_engine import analyze_geometry, compute_reading_order
    blocks = [
        {"type": "paragraph", "content": "Account No:", "x1": 10, "y1": 20, "x2": 110, "y2": 38, "confidence": 0.93, "page": 0},
        {"type": "paragraph", "content": "123456789", "x1": 115, "y1": 21, "x2": 230, "y2": 38, "confidence": 0.97, "page": 0},
        {"type": "paragraph", "content": "Balance", "x1": 10, "y1": 55, "x2": 80, "y2": 72, "confidence": 0.90, "page": 0},
        {"type": "paragraph", "content": "5000.00", "x1": 85, "y1": 55, "x2": 150, "y2": 72, "confidence": 0.88, "page": 0},
    ]
    geo = analyze_geometry(blocks, 600.0, 800.0)
    assert len(geo) == 4, f"should return 4 blocks, got {len(geo)}"
    # Every block should have row_band and col_band
    for b in geo:
        assert "row_band" in b, f"missing row_band: {b}"
        assert "col_band" in b, f"missing col_band: {b}"
        assert "cx" in b, f"missing cx: {b}"
    # reading order
    ordered = compute_reading_order(geo, 600.0, [(0.0, 600.0)])
    orders = [b["reading_order"] for b in ordered]
    assert len(orders) == 4
    print(f"    reading_order: {orders}")
    # Label-value detection: "Account No:" should link to "123456789"
    label_blocks = [b for b in geo if b.get("value_for_id") is not None]
    print(f"    label-value pairs detected: {len(label_blocks)}")

test("analyze_geometry", test_geometry)

# ── 4. word_confidence_normalizer ──────────────────────────────────────────────
def test_confidence_normalizer():
    from app.extraction.word_confidence_normalizer import (
        normalize_tesseract_conf, normalize_paddle_conf, normalize_easyocr_conf,
        aggregate_line_confidence, compute_confidence_cascade, enrich_blocks_with_confidence
    )
    # Tesseract raw 85 should produce < 0.80 after calibration
    t = normalize_tesseract_conf(85)
    assert 0.5 < t < 0.90, f"tesseract 85 -> {t}"
    # Paddle 0.92 should stay near 0.92
    p = normalize_paddle_conf(0.92)
    assert 0.88 < p < 0.99, f"paddle 0.92 -> {p}"
    # EasyOCR low score should be boosted
    e_low = normalize_easyocr_conf(0.35)
    assert e_low > 0.35, f"easyocr 0.35 should be boosted: {e_low}"
    # Harmonic mean of [0.9, 0.9, 0.1] should be way below mean
    hm = aggregate_line_confidence([0.9, 0.9, 0.1], method="harmonic_mean")
    arith = (0.9 + 0.9 + 0.1) / 3
    assert hm < arith, f"harmonic mean {hm} should be < arithmetic mean {arith}"
    # Cascade
    cascade = compute_confidence_cascade(0.92, 0.88, 0.81, 0.76)
    assert "overallConfidence" in cascade
    assert cascade["overallConfidence"] < 0.92, f"overall should be < ocr: {cascade}"
    print(f"    cascade: {cascade}")
    # Block enrichment
    blocks = [{"type": "paragraph", "content": "test", "x1": 0, "y1": 0, "x2": 100, "y2": 20,
               "confidence": 85, "engine": "tesseract"}]
    enriched = enrich_blocks_with_confidence(blocks, "tesseract")
    assert 0 < enriched[0]["confidence"] < 1, f"normalized conf should be 0..1: {enriched[0]['confidence']}"

test("word_confidence_normalizer", test_confidence_normalizer)

# ── 5. debug_visualizer ────────────────────────────────────────────────────────
def test_debug_visualizer():
    import numpy as np
    from app.extraction.debug_visualizer import visualize_layout, visualize_reading_order
    bgr = np.ones((600, 800, 3), dtype="uint8") * 240  # light gray
    blocks = [
        {"type": "header", "content": "Header", "x1": 50, "y1": 20, "x2": 400, "y2": 50, "reading_order": 0},
        {"type": "paragraph", "content": "Body text here", "x1": 50, "y1": 80, "x2": 500, "y2": 110, "reading_order": 1},
    ]
    lines = [
        {"text": "Header", "x1": 50, "y1": 20, "x2": 400, "y2": 50, "confidence": 0.95},
    ]
    out = visualize_layout(bgr, blocks=blocks, lines=lines, tables=[], columns=[], page_idx=0)
    assert out is not None
    assert out.shape[2] == 3
    ro_img = visualize_reading_order(bgr, blocks)
    assert ro_img is not None
    print(f"    visualize_layout output shape: {out.shape}")

test("debug_visualizer", test_debug_visualizer)

# ── 6. ocr_cache ──────────────────────────────────────────────────────────────
def test_ocr_cache():
    from app.extraction.ocr_cache import OCRCache
    cache = OCRCache()
    fake_bytes = b"test document content 12345"
    cache.invalidate(fake_bytes)
    fake_result = {"text": "hello", "lines": [{"text": "hello"}], "engine": "tesseract"}
    # Should miss
    hit = cache.get(fake_bytes)
    assert hit is None, f"should be a cache miss on first call"
    # Set and get
    cache.set(fake_bytes, fake_result)
    hit2 = cache.get(fake_bytes)
    assert hit2 is not None, "should be a cache hit after set()"
    assert hit2.get("text") == "hello"
    # Stage cache
    cache.set_stage(fake_bytes, "lines", [{"text": "line1"}])
    stage = cache.get_stage(fake_bytes, "lines")
    assert stage is not None
    # Invalidate
    cache.invalidate(fake_bytes)
    hit3 = cache.get(fake_bytes)
    assert hit3 is None, "should miss after invalidate"
    stats = cache.stats()
    print(f"    cache stats: {stats}")

test("ocr_cache", test_ocr_cache)

# ── Summary ────────────────────────────────────────────────────────────────────
print()
print(f"{'='*50}")
print(f"PHASE 1 SMOKE TEST RESULTS")
print(f"  PASSED: {len(PASS)}/{len(PASS)+len(FAIL)}")
if FAIL:
    print(f"  FAILED: {len(FAIL)}")
    for name, err in FAIL:
        print(f"    - {name}: {err}")
else:
    print(f"  ALL TESTS PASSED")
print(f"{'='*50}")
sys.exit(0 if not FAIL else 1)
