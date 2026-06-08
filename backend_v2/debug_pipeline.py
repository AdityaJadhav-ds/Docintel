import json, cv2, sys, os, pathlib
sys.path.insert(0, '.')

pathlib.Path('debug').mkdir(exist_ok=True)

from ocr_engine import extract_text_from_image
from table_reconstruction import normalize_paddle_result
from line_builder import build_lines
from section_detector import detect_sections
from table_engine import build_grid

# Use last debug image or test image
img_path = 'debug_p0_ocr.jpg' if os.path.exists('debug_p0_ocr.jpg') else 'test_ocr.jpg'
img = cv2.imread(img_path)
if img is None:
    print("ERROR: no image found"); sys.exit(1)

h, w = img.shape[:2]
print(f"Image: {w}x{h}  from {img_path}")

# ── Layer 2: OCR ──────────────────────────────────────────────────────────────
raw = extract_text_from_image(img)
if raw and isinstance(raw, list):
    raw = raw[0]
boxes = normalize_paddle_result(raw)
print(f"\nBOXES: {len(boxes)}")
for b in boxes[:5]:
    print(f"  {b['text']!r:30}  cx={b['cx']:.0f}  cy={b['cy']:.0f}  h={b['height']:.0f}")

with open('debug/raw_boxes.json', 'w') as f:
    json.dump(boxes, f, indent=2, default=str)
print("  -> debug/raw_boxes.json written")

# ── Layer 3: Lines ────────────────────────────────────────────────────────────
lines = build_lines(boxes)
print(f"\nLINES: {len(lines)}")
for i, l in enumerate(lines[:15]):
    nb = l['n_boxes']
    txt = l['text'][:70]
    print(f"  [{i:2d}] n={nb}  y={l['cy']:.0f}  x1={l['x1']:.0f}  x2={l['x2']:.0f}  | {txt!r}")

with open('debug/lines.json', 'w') as f:
    data = [{'text': l['text'], 'n_boxes': l['n_boxes'],
             'y1': round(l['y1'],1), 'y2': round(l['y2'],1),
             'x1': round(l['x1'],1), 'x2': round(l['x2'],1)} for l in lines]
    json.dump(data, f, indent=2)
print("  -> debug/lines.json written")

# ── Layer 4: Sections ─────────────────────────────────────────────────────────
sections = detect_sections(lines, page_width=w)
hl = sections['header_lines']
tl = sections['table_lines']
fl = sections['footer_lines']
cols = sections['columns']

print(f"\nSECTIONS:")
print(f"  header_lines: {len(hl)}")
print(f"  table_lines:  {len(tl)}")
print(f"  footer_lines: {len(fl)}")
print(f"  columns ({len(cols)}): {cols}")

# Print table lines
print("\nTABLE LINES:")
for i, l in enumerate(tl[:15]):
    nb = l['n_boxes']
    txt = l['text'][:80]
    print(f"  [{i:2d}] n={nb}  | {txt!r}")

with open('debug/sections.json', 'w') as f:
    json.dump({
        'header_count': len(hl),
        'table_count':  len(tl),
        'footer_count': len(fl),
        'columns':      cols,
        'table_lines':  [{'text': l['text'], 'n_boxes': l['n_boxes']} for l in tl],
    }, f, indent=2)
print("  -> debug/sections.json written")

# ── Layer 5: Grid ─────────────────────────────────────────────────────────────
grid = build_grid(tl, cols)
print(f"\nGRID: {len(grid)} rows x {len(cols)} cols")
for i, row in enumerate(grid[:12]):
    print(f"  [{i:2d}] {row}")

with open('debug/grid.json', 'w') as f:
    json.dump(grid, f, indent=2)
print("  -> debug/grid.json written")

print("\n=== DONE ===")
