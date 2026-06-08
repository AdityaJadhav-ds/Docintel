"""
ocr_deep_profile.py
====================
Stage-by-stage breakdown of where 15 seconds go inside the KYC OCR path.

Measures:
  1. File load / decode
  2. Image render (PDFâ†’BGR) + image dimensions
  3. Grayscale conversion
  4. _is_noisy() check + denoising (if triggered)
  5. OCR detection (text region finding)
  6. OCR recognition (text reading per box)
  7. Geometry / flatten_paddle_result
  8. group_rows (reading order)
  9. Regex extraction (_extract_kyc_fields)
 10. Supabase save

Usage:
    cd backend
    venv\\Scripts\\python.exe ocr_deep_profile.py
"""
import sys, os, io, time, logging
sys.stdout.reconfigure(encoding="utf-8")   # prevent cp1252 crash on Windows
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ["FLAGS_enable_pir_api"]        = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)   # silence everything

import cv2
import numpy as np

# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
T = {}

def tick(label):
    T[label] = time.monotonic()

def tock(label):
    return int((time.monotonic() - T[label]) * 1000)

def section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")

def row(label, ms, note=""):
    bar = "#" * max(1, ms // 500)
    print(f"  {label:<28} {ms:>7}ms  {bar}  {note}")

# â”€â”€ Load the KYC OCR engine (already warm from prior runs in this process) â”€â”€â”€
section("LOADING OCR ENGINE")
tick("engine_init")
from app.extraction.pipeline import _get_ocr, _is_noisy
from app.extraction.pdf import render_pages
from app.extraction.geometry import flatten_paddle_result, group_rows
from app.services.ocr_pipeline import _extract_kyc_fields

ocr = _get_ocr("kyc")
engine_init_ms = tock("engine_init")
print(f"  Engine loaded in {engine_init_ms}ms  (0ms if already singleton)")

# Try to detect internal PaddleX sub-models for split det/rec timing
has_internal = False
try:
    # PaddleX 3.x: ocr object has _pipeline which has _models
    pipeline = getattr(ocr, "_pipeline", None) or ocr
    det_model = getattr(pipeline, "text_det_model", None)
    rec_model = getattr(pipeline, "text_rec_model", None)
    if det_model and rec_model:
        has_internal = True
        print("  PaddleX internal det/rec models accessible â€” split timing enabled.")
    else:
        print("  Internal models not directly accessible â€” will time full predict().")
except Exception:
    print("  Internal model access failed â€” will time full predict().")

# â”€â”€ Download Aadhaar doc 31 â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
section("DOWNLOADING AADHAAR (doc 31)")
from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document

tick("download")
sb  = get_supabase()
doc = sb.table("documents").select("*").eq("id", 31).single().execute().data
raw_bytes = _download_document(doc["storage_path"])
dl_ms = tock("download")
print(f"  Downloaded {len(raw_bytes)} bytes in {dl_ms}ms")

# â”€â”€ Profile each stage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
section("STAGE-BY-STAGE PROFILE â€” AADHAAR")

# 1. File decode / format detection
tick("file_decode")
is_pdf = raw_bytes[:4] == b"%PDF"
filename = "doc.pdf" if is_pdf else "doc.jpg"
_ = len(raw_bytes)
decode_ms = tock("file_decode")

# 2. Render to image
tick("render")
pages = render_pages(raw_bytes, filename)
render_ms = tock("render")
bgr = pages[0]
h, w = bgr.shape[:2]
print(f"  Image dimensions: {w} x {h} pixels  ({w*h//1000}K pixels)")
print(f"  Image size in RAM: {bgr.nbytes//1024} KB")

# 3. Grayscale conversion
tick("grayscale")
gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
gray_ms = tock("grayscale")

# 4. Noise check
tick("noise_check")
noisy = _is_noisy(gray)
noise_ms = tock("noise_check")

# 5. Denoising (if triggered)
denoise_ms = 0
if noisy:
    tick("denoise")
    gray = cv2.fastNlMeansDenoising(gray, None, h=10, templateWindowSize=7, searchWindowSize=21)
    denoise_ms = tock("denoise")

# 6. OCR â€” try to split det vs rec, otherwise time full call
ocr_img = bgr   # pipeline uses bgr, not gray
det_ms = rec_ms = full_ocr_ms = 0
raw_result = None

if has_internal:
    try:
        # Detection pass
        tick("det")
        det_boxes = det_model.predict(ocr_img)
        det_ms = tock("det")
        
        # Recognition pass
        tick("rec")
        raw_result = rec_model.predict(ocr_img, det_boxes)
        rec_ms = tock("rec")
    except Exception as e:
        print(f"  Split timing failed ({e}), falling back to full predict()")
        has_internal = False

if not has_internal:
    tick("full_ocr")
    if hasattr(ocr, "predict"):
        raw_result = ocr.predict(ocr_img)
    else:
        raw_result = ocr.ocr(ocr_img, cls=False)
    full_ocr_ms = tock("full_ocr")

# 7. Geometry: flatten result
tick("flatten")
flat = raw_result
if flat and isinstance(flat[0], list):
    flat = flat[0]
boxes = flatten_paddle_result(flat or [])
flatten_ms = tock("flatten")

# 8. Group rows (reading order)
tick("group_rows")
rows_grouped = group_rows(boxes)
page_text = "\n".join(" ".join(b["text"] for b in r) for r in rows_grouped)
group_ms = tock("group_rows")

# 9. Regex extraction
tick("regex")
extracted = _extract_kyc_fields(page_text, "aadhaar")
regex_ms = tock("regex")

# 10. Supabase save (dry run â€” measure the round trip)
tick("supabase_check")
_ = sb.table("documents").select("id").eq("id", 31).execute()
supabase_ms = tock("supabase_check")

# â”€â”€ Print table â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
print()
row("1. Download",          dl_ms,          f"({len(raw_bytes)//1024}KB from Supabase)")
row("2. File decode",       decode_ms,      f"({'PDF' if is_pdf else 'IMG'})")
row("3. Render to image",   render_ms,      f"â†’ {w}Ã—{h}px  {bgr.nbytes//1024}KB RAM")
row("4. Grayscale",         gray_ms)
row("5. Noise check",       noise_ms,       f"noisy={noisy}")
row("6. Denoising",         denoise_ms,     "SKIPPED" if not noisy else "TRIGGERED â† expensive!")
if has_internal:
    row("7a. Detection (det)", det_ms,      f"{len(det_boxes) if det_boxes else '?'} boxes")
    row("7b. Recognition (rec)", rec_ms,    f"{len(boxes)} text lines")
else:
    row("7. OCR predict()",  full_ocr_ms,   f"â†’ {len(boxes)} boxes (det+rec combined)")
row("8. Flatten/geometry",  flatten_ms,     f"{len(boxes)} boxes")
row("9. Group rows",        group_ms)
row("10. Regex extraction", regex_ms,       str(extracted)[:60])
row("11. Supabase ping",    supabase_ms,    "(read-only check)")

total_pipeline = (dl_ms + decode_ms + render_ms + gray_ms + noise_ms + denoise_ms +
                  det_ms + rec_ms + full_ocr_ms + flatten_ms + group_ms + regex_ms)
print(f"\n  {'TOTAL (profiled)':<28} {total_pipeline:>7}ms")

section("ANSWERS")
print(f"  Image fed to OCR:  {w} Ã— {h} pixels  ({w*h:,} total pixels)")
print(f"  Is denoising triggered: {noisy}")
print(f"  Boxes found: {len(boxes)}")
print(f"  Words found: {sum(len(b['text'].split()) for b in boxes)}")
print(f"  Extracted fields: {extracted}")
print()
if full_ocr_ms:
    pct = full_ocr_ms / max(total_pipeline, 1) * 100
    print(f"  OCR predict() alone = {full_ocr_ms}ms = {pct:.0f}% of total pipeline time")
    print()
    # Estimate what 3x image downscale would do
    pixels = w * h
    print(f"  HYPOTHESIS â€” if image downscaled to 1200px wide:")
    ratio = min(1.0, 1200 / w)
    scaled_pixels = int(pixels * ratio * ratio)
    print(f"    Pixel count: {pixels:,} â†’ {scaled_pixels:,}  ({100*(1-ratio**2):.0f}% reduction)")
    est_ms = int(full_ocr_ms * ratio * ratio)
    print(f"    Estimated OCR time: {full_ocr_ms}ms â†’ ~{est_ms}ms")
print()

