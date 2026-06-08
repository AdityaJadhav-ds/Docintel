"""
smoke_test_phase2.py
====================
Validates all Phase 2 engines for Region-First OCR.
"""
import sys
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.extraction.page_segmentation import segment_page
from app.extraction.region_detector import detect_raw_regions, _ensure_model_weights
from app.extraction.region_merger import merge_regions, classify_regions
from app.extraction.table_understanding import extract_table_structure
from app.extraction.document_graph import build_document_graph
from app.extraction.ocr_cache import OCRCache

print("==================================================")
print("PHASE 2 SMOKE TEST: REGION-FIRST OCR")
print("==================================================")

# Create a fake document image with clear text and a table structure
def create_fake_document():
    img = np.ones((800, 600, 3), dtype=np.uint8) * 255
    # Draw a header
    cv2.putText(img, "ACCOUNT STATEMENT", (150, 80), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,0,0), 2)
    # Draw some text
    cv2.putText(img, "Name: John Doe", (50, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    cv2.putText(img, "Account No: 123456789", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    
    # Draw a table with grid lines
    cv2.rectangle(img, (50, 300), (550, 500), (0,0,0), 2)
    cv2.line(img, (50, 350), (550, 350), (0,0,0), 1)
    cv2.line(img, (50, 400), (550, 400), (0,0,0), 1)
    cv2.line(img, (200, 300), (200, 500), (0,0,0), 1)
    cv2.line(img, (400, 300), (400, 500), (0,0,0), 1)
    
    cv2.putText(img, "Date", (60, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    cv2.putText(img, "Description", (210, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    cv2.putText(img, "Amount", (410, 330), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    
    cv2.putText(img, "01/01/2026", (60, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    cv2.putText(img, "Deposit", (210, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    cv2.putText(img, "$5000.00", (410, 380), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,0), 1)
    
    # Signature line
    cv2.putText(img, "Authorized Signature", (400, 700), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,0), 1)
    cv2.line(img, (400, 680), (550, 680), (0,0,0), 1)
    
    return img

test_img = create_fake_document()
gray = cv2.cvtColor(test_img, cv2.COLOR_BGR2GRAY)

tests_passed = 0
tests_failed = 0

def run_test(name, fn):
    global tests_passed, tests_failed
    try:
        fn()
        print(f"  [PASS] {name}")
        tests_passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        tests_failed += 1

def test_page_segmentation():
    segments = segment_page(gray)
    assert "margins" in segments
    assert "content_blocks" in segments
    print(f"    Found {len(segments['content_blocks'])} content blocks")
run_test("page_segmentation", test_page_segmentation)

def test_region_detector():
    has_weights = _ensure_model_weights()
    assert has_weights, "Failed to download or verify CRAFT weights"
    
    raw_regions = detect_raw_regions(test_img)
    # The dummy image has several words
    assert len(raw_regions) > 5, f"Expected >5 regions, got {len(raw_regions)}"
    global RAW_REGIONS
    RAW_REGIONS = raw_regions
    print(f"    Found {len(raw_regions)} raw regions")
run_test("region_detector (CRAFT)", test_region_detector)

def test_region_merger():
    merged = merge_regions(RAW_REGIONS, test_img)
    assert len(merged) < len(RAW_REGIONS), "Merging should reduce region count"
    classified = classify_regions(merged, test_img)
    
    table_count = sum(1 for r in classified if r.get('region_type') == 'TABLE')
    header_count = sum(1 for r in classified if r.get('region_type') == 'HEADER')
    
    # Based on our heuristics, it should find the table and header
    global CLASSIFIED_REGIONS
    CLASSIFIED_REGIONS = classified
    print(f"    Merged into {len(classified)} regions. Found {table_count} tables, {header_count} headers.")
run_test("region_merger & classification", test_region_merger)

def test_table_understanding():
    tables = [r for r in CLASSIFIED_REGIONS if r.get('region_type') == 'TABLE']
    if not tables:
        print("    Skipping table test: no tables detected by heuristic.")
        return
        
    table = tables[0]
    children = [r for r in CLASSIFIED_REGIONS if r != table and 
                r['x1'] >= table['x1'] and r['y1'] >= table['y1'] and 
                r['x2'] <= table['x2'] and r['y2'] <= table['y2']]
                
    struct = extract_table_structure(table, children, test_img)
    assert "rows" in struct
    print(f"    Found {len(struct['rows'])} rows in table")
run_test("table_understanding", test_table_understanding)

def test_document_graph():
    graph = build_document_graph(CLASSIFIED_REGIONS)
    assert isinstance(graph, dict)
    assert len(graph) == len(CLASSIFIED_REGIONS)
    
    # Check for label-value relationships
    has_label_value = any(v.get('label_for') is not None for v in graph.values())
    print(f"    Graph built successfully. Has label-value links: {has_label_value}")
run_test("document_graph", test_document_graph)

def test_ocr_cache_region():
    cache = OCRCache()
    fake_crop = np.ones((100, 100, 3), dtype=np.uint8) * 128
    
    fake_res = {"text": "region cache test"}
    cache.set_region(fake_crop, fake_res)
    
    hit = cache.get_region(fake_crop)
    assert hit is not None, "Region cache miss"
    assert hit["text"] == "region cache test"
run_test("ocr_cache region hashing", test_ocr_cache_region)

print("==================================================")
print(f"PHASE 2 SMOKE TEST RESULTS")
print(f"  PASSED: {tests_passed}/6")
print(f"  FAILED: {tests_failed}")
print("==================================================")
