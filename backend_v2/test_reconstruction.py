"""
test_reconstruction.py
Direct test of the reconstruction pipeline with realistic OCR word boxes.
Bypasses PaddleOCR - feeds word boxes directly into the layout stack.
Simulates the broken output from the screenshots (Branch/Code split, etc.)
"""
import sys
sys.path.insert(0, '.')

from layout_tree import Word, Line, Region
from normalizer import normalize_boxes
from line_engine import build_lines
from phrase_merger import merge_phrases
from region_engine import detect_regions
from table_engine import process_table_region
from kv_renderer import process_kv_region

# ─── Simulate OCR boxes from the SBI statement screenshot ────────────────────
# These mirror the fragmented OCR words causing the visual corruption
raw_boxes = [
    # Header - top section
    {"text": "SBI",        "x1": 50,  "y1": 10,  "x2": 80,  "y2": 25,  "cx": 65,  "cy": 17, "width": 30,  "height": 15},
    {"text": "STATEMENT",  "x1": 200, "y1": 60,  "x2": 300, "y2": 75,  "cx": 250, "cy": 67, "width": 100, "height": 15},
    {"text": "OF",         "x1": 305, "y1": 60,  "x2": 325, "y2": 75,  "cx": 315, "cy": 67, "width": 20,  "height": 15},
    {"text": "ACCOUNT",    "x1": 330, "y1": 60,  "x2": 430, "y2": 75,  "cx": 380, "cy": 67, "width": 100, "height": 15},

    # KV block - these were being exploded before
    {"text": "Branch",     "x1": 50,  "y1": 100, "x2": 110, "y2": 115, "cx": 80,  "cy": 107, "width": 60,  "height": 15},
    {"text": "Code",       "x1": 113, "y1": 100, "x2": 155, "y2": 115, "cx": 134, "cy": 107, "width": 42,  "height": 15},
    {"text": ":",          "x1": 160, "y1": 100, "x2": 165, "y2": 115, "cx": 162, "cy": 107, "width": 5,   "height": 15},
    {"text": "8234",       "x1": 170, "y1": 100, "x2": 210, "y2": 115, "cx": 190, "cy": 107, "width": 40,  "height": 15},

    {"text": "IFSC",       "x1": 50,  "y1": 120, "x2": 90,  "y2": 135, "cx": 70,  "cy": 127, "width": 40,  "height": 15},
    {"text": "Code",       "x1": 93,  "y1": 120, "x2": 133, "y2": 135, "cx": 113, "cy": 127, "width": 40,  "height": 15},
    {"text": ":",          "x1": 138, "y1": 120, "x2": 143, "y2": 135, "cx": 140, "cy": 127, "width": 5,   "height": 15},
    {"text": "KKBK0002046","x1": 148, "y1": 120, "x2": 260, "y2": 135, "cx": 204, "cy": 127, "width": 112, "height": 15},

    {"text": "Account",    "x1": 50,  "y1": 140, "x2": 110, "y2": 155, "cx": 80,  "cy": 147, "width": 60,  "height": 15},
    {"text": "No",         "x1": 113, "y1": 140, "x2": 140, "y2": 155, "cx": 126, "cy": 147, "width": 27,  "height": 15},
    {"text": ":",          "x1": 145, "y1": 140, "x2": 150, "y2": 155, "cx": 147, "cy": 147, "width": 5,   "height": 15},
    {"text": "8850687756", "x1": 155, "y1": 140, "x2": 265, "y2": 155, "cx": 210, "cy": 147, "width": 110, "height": 15},

    # Table header row
    {"text": "Date",        "x1": 50,  "y1": 200, "x2": 100, "y2": 215, "cx": 75,  "cy": 207, "width": 50,  "height": 15},
    {"text": "Description", "x1": 160, "y1": 200, "x2": 280, "y2": 215, "cx": 220, "cy": 207, "width": 120, "height": 15},
    {"text": "Debit",       "x1": 350, "y1": 200, "x2": 400, "y2": 215, "cx": 375, "cy": 207, "width": 50,  "height": 15},
    {"text": "Credit",      "x1": 430, "y1": 200, "x2": 490, "y2": 215, "cx": 460, "cy": 207, "width": 60,  "height": 15},
    {"text": "Balance",     "x1": 520, "y1": 200, "x2": 590, "y2": 215, "cx": 555, "cy": 207, "width": 70,  "height": 15},

    # Table row 1
    {"text": "02",          "x1": 50,  "y1": 220, "x2": 68,  "y2": 235, "cx": 59,  "cy": 227, "width": 18,  "height": 15},
    {"text": "Feb",         "x1": 70,  "y1": 220, "x2": 100, "y2": 235, "cx": 85,  "cy": 227, "width": 30,  "height": 15},
    {"text": "UPI/Shridhan","x1": 160, "y1": 220, "x2": 270, "y2": 235, "cx": 215, "cy": 227, "width": 110, "height": 15},
    {"text": "66.00",       "x1": 355, "y1": 220, "x2": 400, "y2": 235, "cx": 377, "cy": 227, "width": 45,  "height": 15},
    {"text": "4445",        "x1": 525, "y1": 220, "x2": 575, "y2": 235, "cx": 550, "cy": 227, "width": 50,  "height": 15},

    # Continuation row (description wraps to next line)
    {"text": "from",        "x1": 160, "y1": 238, "x2": 195, "y2": 253, "cx": 177, "cy": 245, "width": 35,  "height": 15},
    {"text": "Ph",          "x1": 198, "y1": 238, "x2": 218, "y2": 253, "cx": 208, "cy": 245, "width": 20,  "height": 15},

    # Table row 2
    {"text": "03",          "x1": 50,  "y1": 260, "x2": 68,  "y2": 275, "cx": 59,  "cy": 267, "width": 18,  "height": 15},
    {"text": "Feb",         "x1": 70,  "y1": 260, "x2": 100, "y2": 275, "cx": 85,  "cy": 267, "width": 30,  "height": 15},
    {"text": "NEFT",        "x1": 160, "y1": 260, "x2": 200, "y2": 275, "cx": 180, "cy": 267, "width": 40,  "height": 15},
    {"text": "TRANSFER",    "x1": 203, "y1": 260, "x2": 275, "y2": 275, "cx": 239, "cy": 267, "width": 72,  "height": 15},
    {"text": "500.00",      "x1": 352, "y1": 260, "x2": 400, "y2": 275, "cx": 376, "cy": 267, "width": 48,  "height": 15},
    {"text": "3945",        "x1": 525, "y1": 260, "x2": 575, "y2": 275, "cx": 550, "cy": 267, "width": 50,  "height": 15},
]

PAGE_W = 700
PAGE_H = 1000

print("=" * 60)
print("RECONSTRUCTION PIPELINE TEST")
print("=" * 60)

# Step 1: normalize
words = normalize_boxes(raw_boxes)
print(f"\nStep 1 normalize: {len(raw_boxes)} boxes -> {len(words)} words")

# Step 2: build lines
lines = build_lines(words)
print(f"Step 2 lines:     {len(words)} words -> {len(lines)} lines")
for l in lines:
    print(f"  y={l.cy:5.0f}  words={len(l.words):2d}  text={repr(l.text[:70])}")

# Step 3: phrase merging
merged = merge_phrases(lines)
print(f"\nStep 3 phrases:   {sum(len(l.words) for l in lines)} words -> {sum(len(l.words) for l in merged)} phrases")
for l in merged:
    phrases = [w.text for w in l.words]
    print(f"  y={l.cy:5.0f}  phrases={phrases}")

# Step 4: region detection
regions = detect_regions(merged, PAGE_W, PAGE_H)
print(f"\nStep 4 regions:   {len(regions)} detected")
for r in regions:
    print(f"  [{r.region_id}] type={r.region_type:10s}  lines={len(r.lines)}")

# Step 5: process each region
print("\nStep 5 structured output:")
print("-" * 60)
for r in regions:
    print(f"\nREGION [{r.region_id}] — {r.region_type.upper()}")

    if r.region_type == "table":
        result = process_table_region(r)
        anchors = [round(a) for a in result.get("anchors", [])]
        grid = result.get("grid", [])
        print(f"  Anchors: {anchors}")
        print(f"  Grid ({result['n_cols']} cols x {result['n_rows']} rows):")
        for row in grid:
            print(f"    {row}")
        print(f"  raw_lines: {result['raw_lines']}")

    elif r.region_type == "kv_block":
        result = process_kv_region(r)
        print(f"  Pairs:")
        for p in result["pairs"]:
            print(f"    {repr(p['key'])} : {repr(p['value'])}")
        print(f"  raw_lines: {result['raw_lines']}")

    else:
        print(f"  Text: {repr(chr(10).join(l.text for l in r.lines))}")

# Final assertions
print("\n" + "=" * 60)
print("ASSERTIONS")
print("=" * 60)

kv_regions = [r for r in regions if r.region_type == "kv_block"]
table_regions = [r for r in regions if r.region_type == "table"]

assert len(kv_regions) >= 1, "Expected at least 1 kv_block region"
print("PASS: kv_block region detected")

kv_content = kv_regions[0].content
kv_keys = [p["key"] for p in kv_content["pairs"]]
# "Branch Code" should be a single phrase key (not exploded)
branch_key = next((k for k in kv_keys if "Branch" in k), None)
assert branch_key is not None, f"Branch Code not found in KV keys: {kv_keys}"
assert "Code" in branch_key, f"'Branch' and 'Code' not merged into one key: {branch_key}"
print(f"PASS: 'Branch Code' merged correctly -> key={repr(branch_key)}")

assert len(table_regions) >= 1, "Expected at least 1 table region"
print("PASS: table region detected")

table_content = table_regions[0].content
assert "raw_lines" in table_content, "raw_lines missing from table content"
print("PASS: raw_lines present in table content")

grid = table_content.get("grid", [])
assert len(grid) >= 1, "Table grid is empty"
print(f"PASS: Table grid has {len(grid)} rows x {table_content['n_cols']} cols")

# Check continuation row was merged
row_texts = [" ".join(c for c in row if c) for row in grid]
merged_row = next((t for t in row_texts if "UPI" in t and "from Ph" in t), None)
assert merged_row is not None, f"Continuation row not merged. Rows: {row_texts}"
print(f"PASS: Continuation row merged -> {repr(merged_row[:60])}")

print("\nALL ASSERTIONS PASSED")
