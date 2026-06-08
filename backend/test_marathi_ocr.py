"""
test_marathi_ocr.py  --  STANDALONE OCR DIAGNOSTIC
Run: venv\Scripts\python.exe test_marathi_ocr.py [image_path]
"""
import sys, os, time
os.environ["PYTHONIOENCODING"] = "utf-8"
sys.stdout.reconfigure(encoding="utf-8")

import cv2
import numpy as np
from PIL import Image as PILImage

# ── 1. Tesseract setup ────────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1 -- TESSERACT ENVIRONMENT")
print("=" * 60)

# import pytesseract

known = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.isfile(known):
    pytesseract.pytesseract.tesseract_cmd = known
    print(f"  cmd: {known}")
else:
    import shutil
    cmd = shutil.which("tesseract")
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
        print(f"  cmd: {cmd}")
    else:
        print("  ERROR: tesseract not found")
        sys.exit(1)

langs = pytesseract.get_languages(config="")
print(f"  langs: {langs}")
print(f"  mar present: {'mar' in langs}")

# ── 2. Load image ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 2 -- IMAGE LOAD")
print("=" * 60)

image_path = sys.argv[1] if len(sys.argv) > 1 else None

if image_path and os.path.isfile(image_path):
    bgr = cv2.imread(image_path)
    print(f"  loaded: {image_path}")
else:
    print("  No image path given -- using synthetic test image")
    print("  Run with: python test_marathi_ocr.py path/to/ration_card.jpg")
    bgr = np.ones((600, 800, 3), dtype=np.uint8) * 200
    cv2.rectangle(bgr, (50, 80), (750, 130), (60, 60, 60), -1)
    cv2.putText(bgr, "SYNTHETIC TEST 123 ABC", (60, 115),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (220, 220, 220), 2)

if bgr is None:
    print("  ERROR: image is None (could not decode)")
    sys.exit(1)

h, w = bgr.shape[:2]
print(f"  shape : {bgr.shape}")
print(f"  dtype : {bgr.dtype}")
print(f"  min   : {bgr.min()}")
print(f"  max   : {bgr.max()}")
print(f"  mean  : {bgr.mean():.1f}")
print(f"  std   : {bgr.std():.1f}")

cv2.imwrite("debug_ocr_input_original.png", bgr)
print("  Saved: debug_ocr_input_original.png")

# ── 3. Grayscale ─────────────────────────────────────────────────────────────
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
print()
print(f"  gray min={gray.min()} max={gray.max()} mean={gray.mean():.1f} std={gray.std():.1f}")
cv2.imwrite("debug_ocr_input_gray.png", gray)

# ── 4. Raw OCR tests ─────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 4 -- RAW TESSERACT (no preprocessing)")
print("=" * 60)

pil = PILImage.fromarray(gray)

for lang, psm in [("mar", 3), ("mar", 6), ("hin", 3), ("mar+hin", 3), ("eng", 3)]:
    try:
        t0 = time.monotonic()
        text = pytesseract.image_to_string(pil, lang=lang, config=f"--oem 1 --psm {psm}")
        ms = int((time.monotonic() - t0) * 1000)
        chars = len(text.strip())
        preview = repr(text.strip()[:80]) if chars else "(empty)"
        print(f"  lang={lang:<12} psm={psm}  chars={chars:4d}  {ms}ms  {preview}")
    except Exception as e:
        print(f"  lang={lang:<12} psm={psm}  ERROR: {e}")

# ── 5. TSV detail ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 5 -- TSV word count (mar, psm=3)")
print("=" * 60)

try:
    t0 = time.monotonic()
    tsv = pytesseract.image_to_data(pil, lang="mar", config="--oem 1 --psm 3",
                                    output_type=pytesseract.Output.DICT)
    ms = int((time.monotonic() - t0) * 1000)
    valid = [(tsv["text"][i], tsv["conf"][i])
             for i in range(len(tsv["text"]))
             if str(tsv["text"][i]).strip() and str(tsv["conf"][i]) not in ("-1", "-1.0")]
    print(f"  TSV rows={len(tsv['text'])}  valid_words={len(valid)}  {ms}ms")
    for word, conf in valid[:15]:
        print(f"    word={word!r}  conf={conf}")
except Exception as e:
    print(f"  ERROR: {e}")

# ── 6. CLAHE + upscale then OCR ───────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 6 -- CLAHE + 2x upscale then OCR")
print("=" * 60)

try:
    long_side = max(h, w)
    if long_side < 1500:
        scale = 1500 / long_side
        gray_up = cv2.resize(gray, (int(w * scale), int(h * scale)),
                              interpolation=cv2.INTER_CUBIC)
        print(f"  upscaled: {gray.shape[:2]} -> {gray_up.shape[:2]}")
    else:
        gray_up = gray
        print(f"  no upscale needed ({long_side}px)")

    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray_up)
    cv2.imwrite("debug_ocr_input_clahe.png", enhanced)
    print(f"  clahe min={enhanced.min()} max={enhanced.max()} mean={enhanced.mean():.1f}")
    print("  Saved: debug_ocr_input_clahe.png")

    t0 = time.monotonic()
    text = pytesseract.image_to_string(PILImage.fromarray(enhanced), lang="mar",
                                       config="--oem 1 --psm 6")
    ms = int((time.monotonic() - t0) * 1000)
    chars = len(text.strip())
    print(f"  CLAHE OCR: chars={chars}  {ms}ms")
    if text.strip():
        print(f"  TEXT:\n{text.strip()[:500]}")
    else:
        print("  STILL EMPTY after CLAHE")
except Exception as e:
    print(f"  ERROR: {e}")
    import traceback; traceback.print_exc()

# ── 7. core_ocr module test ───────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 7 -- core_ocr module")
print("=" * 60)

sys.path.insert(0, ".")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

try:
    from app.extraction.core_ocr import run_ocr_on_image
    t0 = time.monotonic()
    result = run_ocr_on_image(bgr, lang="mar", psm=3, oem=1)
    ms = int((time.monotonic() - t0) * 1000)
    print(f"  engine    : {result.get('engine')}")
    print(f"  lang      : {result.get('lang')}")
    print(f"  avg_conf  : {result.get('avg_conf', 0):.3f}")
    print(f"  line_boxes: {len(result.get('line_boxes', []))}")
    print(f"  text_len  : {len(result.get('text', ''))}")
    print(f"  elapsed   : {ms}ms")
    txt = result.get('text', '')
    if txt.strip():
        print(f"  TEXT preview: {txt[:300]!r}")
    else:
        print("  WARNING: core_ocr returned EMPTY text")
    if result.get("error"):
        print(f"  ERROR field: {result['error']}")
except Exception as e:
    import traceback
    print(f"  IMPORT/RUN FAILED: {e}")
    traceback.print_exc()

# ── 8. direct pipeline C test ─────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 8 -- Pipeline C (extract_mobile_photo)")
print("=" * 60)

try:
    from app.extraction.core_extractor import extract_mobile_photo
    # encode bgr to bytes
    _, buf = cv2.imencode(".jpg", bgr)
    img_bytes = buf.tobytes()
    t0 = time.monotonic()
    res = extract_mobile_photo(img_bytes, lang="mar")
    ms = int((time.monotonic() - t0) * 1000)
    print(f"  pipeline  : {res.pipeline}")
    print(f"  engine    : {res.engine}")
    print(f"  word_count: {res.word_count}")
    print(f"  pages[0]  : {len(res.pages[0]) if res.pages else 0} chars")
    print(f"  elapsed   : {ms}ms")
    print(f"  notes     : {res.notes}")
    if res.pages and res.pages[0].strip():
        print(f"  TEXT: {res.pages[0][:300]!r}")
    else:
        print("  WARNING: Pipeline C returned EMPTY text")
except Exception as e:
    import traceback
    print(f"  Pipeline C FAILED: {e}")
    traceback.print_exc()

print()
print("=" * 60)
print("DONE -- check debug_ocr_input_*.png files for visual inspection")
print("=" * 60)
