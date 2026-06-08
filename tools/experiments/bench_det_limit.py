"""
bench_det_limit.py
===================
Benchmarks text_det_limit_side_len=640 vs default on Aadhaar + PAN.

Model A:  PP-OCRv3_mobile_det  (default det limit, ~960)
Model B:  PP-OCRv3_mobile_det  (text_det_limit_side_len=640)

Pass criteria:
  1. Runtime improvement >= 20%
  2. Aadhaar number identical
  3. PAN fields identical
  4. Confidence drop <= 2%

Usage:
    cd backend
    venv\\Scripts\\python.exe bench_det_limit.py
"""
import sys, os, io, time, logging
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ["FLAGS_enable_pir_api"]         = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.disable(logging.CRITICAL)

# ── Common pipeline imports ───────────────────────────────────────────────────
from app.extraction.pdf import render_pages
from app.extraction.geometry import flatten_paddle_result, group_rows
from app.services.ocr_pipeline import _extract_kyc_fields
from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document

import cv2, numpy as np
from paddleocr import PaddleOCR

BASE_PARAMS = dict(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
    text_detection_model_name="PP-OCRv3_mobile_det",
    text_recognition_model_name="en_PP-OCRv5_mobile_rec",
)

def section(t): print(f"\n{'='*62}\n{t}\n{'='*62}")
def subsec(t):  print(f"\n  -- {t} --")

# ── Download both docs once ───────────────────────────────────────────────────
section("DOWNLOADING DOCS (once, shared)")
sb = get_supabase()

doc_a = sb.table("documents").select("*").eq("id", 31).single().execute().data
doc_p = sb.table("documents").select("*").eq("id", 32).single().execute().data

aadhaar_bytes = _download_document(doc_a["storage_path"])
pan_bytes     = _download_document(doc_p["storage_path"])

print(f"  Aadhaar: {len(aadhaar_bytes)} bytes")
print(f"  PAN:     {len(pan_bytes)} bytes")

# Pre-render images (exclude render time from OCR benchmark)
aadhaar_bgr = render_pages(aadhaar_bytes, "doc.jpg")[0]
pan_bgr     = render_pages(pan_bytes,     "doc.jpg")[0]
print(f"  Aadhaar image: {aadhaar_bgr.shape[1]}x{aadhaar_bgr.shape[0]}px")
print(f"  PAN image:     {pan_bgr.shape[1]}x{pan_bgr.shape[0]}px")

# ── OCR runner ────────────────────────────────────────────────────────────────
def run_ocr(ocr_engine, bgr, doc_type_hint):
    t0 = time.monotonic()

    if hasattr(ocr_engine, "predict"):
        raw = ocr_engine.predict(bgr)
    else:
        raw = ocr_engine.ocr(bgr, cls=False)

    ocr_ms = int((time.monotonic() - t0) * 1000)

    flat = raw
    if flat and isinstance(flat[0], list):
        flat = flat[0]
    boxes = flatten_paddle_result(flat or [])

    rows  = group_rows(boxes)
    text  = "\n".join(" ".join(b["text"] for b in r) for r in rows)
    conf  = round(sum(b.get("confidence", 0) for b in boxes) / len(boxes), 3) if boxes else 0.0
    extr  = _extract_kyc_fields(text, doc_type_hint)

    return {"ocr_ms": ocr_ms, "text": text, "confidence": conf, "extracted": extr, "boxes": len(boxes)}

# ── Initialise models ─────────────────────────────────────────────────────────
section("INITIALISING MODELS")
print("  Model A: default text_det_limit_side_len ...")
ocr_a = PaddleOCR(**BASE_PARAMS)

print("  Model B: text_det_limit_side_len=640 ...")
ocr_b = PaddleOCR(**BASE_PARAMS, text_det_limit_side_len=640)

# ── Run benchmark ─────────────────────────────────────────────────────────────
results = {}
for label, ocr_engine in [("Model A (default)", ocr_a), ("Model B (limit=640)", ocr_b)]:
    section(f"RUNNING {label}")
    results[label] = {}

    subsec("Aadhaar (doc 31)")
    r = run_ocr(ocr_engine, aadhaar_bgr, "aadhaar")
    results[label]["aadhaar"] = r
    print(f"    OCR time:    {r['ocr_ms']}ms")
    print(f"    Confidence:  {r['confidence']}")
    print(f"    Boxes found: {r['boxes']}")
    print(f"    Extracted:   {r['extracted']}")

    subsec("PAN (doc 32)")
    r = run_ocr(ocr_engine, pan_bgr, "pan")
    results[label]["pan"] = r
    print(f"    OCR time:    {r['ocr_ms']}ms")
    print(f"    Confidence:  {r['confidence']}")
    print(f"    Boxes found: {r['boxes']}")
    print(f"    Extracted:   {r['extracted']}")

# ── Comparison table ──────────────────────────────────────────────────────────
section("COMPARISON TABLE")

ra_a = results["Model A (default)"]["aadhaar"]
ra_b = results["Model B (limit=640)"]["aadhaar"]
rp_a = results["Model A (default)"]["pan"]
rp_b = results["Model B (limit=640)"]["pan"]

def pct_diff(a, b):
    if a == 0: return "N/A"
    return f"{(b - a) / a * 100:+.1f}%"

print(f"\n  {'Metric':<30} {'Model A':>12} {'Model B':>12} {'Delta':>10}")
print(f"  {'-'*66}")
print(f"  {'[AADHAAR]':<30}")
print(f"  {'  OCR time':<30} {ra_a['ocr_ms']:>11}ms {ra_b['ocr_ms']:>11}ms {pct_diff(ra_a['ocr_ms'], ra_b['ocr_ms']):>10}")
print(f"  {'  Confidence':<30} {ra_a['confidence']:>12.3f} {ra_b['confidence']:>12.3f} {pct_diff(ra_a['confidence'], ra_b['confidence']):>10}")
print(f"  {'  Boxes':<30} {ra_a['boxes']:>12} {ra_b['boxes']:>12}")
print(f"  {'[PAN]':<30}")
print(f"  {'  OCR time':<30} {rp_a['ocr_ms']:>11}ms {rp_b['ocr_ms']:>11}ms {pct_diff(rp_a['ocr_ms'], rp_b['ocr_ms']):>10}")
print(f"  {'  Confidence':<30} {rp_a['confidence']:>12.3f} {rp_b['confidence']:>12.3f} {pct_diff(rp_a['confidence'], rp_b['confidence']):>10}")
print(f"  {'  Boxes':<30} {rp_a['boxes']:>12} {rp_b['boxes']:>12}")

# ── Field comparison ──────────────────────────────────────────────────────────
section("FIELD EXTRACTION COMPARISON")
for doc_type in ("aadhaar", "pan"):
    print(f"\n  [{doc_type.upper()}]")
    ea = results["Model A (default)"][doc_type]["extracted"]
    eb = results["Model B (limit=640)"][doc_type]["extracted"]
    all_keys = sorted(set(ea) | set(eb))
    for k in all_keys:
        va, vb = str(ea.get(k, "")), str(eb.get(k, ""))
        match = "IDENTICAL" if va == vb else "DIFFERENT"
        print(f"  {'  '+k:<28} {match}")
        if va != vb:
            print(f"       A: {va[:60]!r}")
            print(f"       B: {vb[:60]!r}")

# ── Pass/fail verdict ─────────────────────────────────────────────────────────
section("PASS / FAIL VERDICT")

speedup_a   = (ra_a["ocr_ms"] - ra_b["ocr_ms"]) / ra_a["ocr_ms"] * 100
speedup_p   = (rp_a["ocr_ms"] - rp_b["ocr_ms"]) / rp_a["ocr_ms"] * 100
conf_drop_a = (ra_a["confidence"] - ra_b["confidence"]) / ra_a["confidence"] * 100
conf_drop_p = (rp_a["confidence"] - rp_b["confidence"]) / rp_a["confidence"] * 100

aadhaar_match = (ra_a["extracted"].get("aadhaar_number") == ra_b["extracted"].get("aadhaar_number"))
pan_name_match = (rp_a["extracted"].get("name") == rp_b["extracted"].get("name"))
pan_dob_match  = (rp_a["extracted"].get("dob")  == rp_b["extracted"].get("dob"))
fields_match   = aadhaar_match and pan_name_match and pan_dob_match

checks = {
    f"Aadhaar OCR speedup >= 20%  ({speedup_a:.1f}%)":   speedup_a >= 20,
    f"PAN OCR speedup >= 20%      ({speedup_p:.1f}%)":   speedup_p >= 20,
    f"Aadhaar number identical":                           aadhaar_match,
    f"PAN name identical":                                 pan_name_match,
    f"PAN dob identical":                                  pan_dob_match,
    f"Aadhaar conf drop <= 2%     ({conf_drop_a:.1f}%)": conf_drop_a <= 2,
    f"PAN conf drop <= 2%         ({conf_drop_p:.1f}%)": conf_drop_p <= 2,
}

all_pass = True
for label, ok in checks.items():
    status = "PASS" if ok else "FAIL"
    if not ok: all_pass = False
    print(f"  [{status}] {label}")

print()
if all_pass:
    print("  ALL CHECKS PASSED -- safe to apply text_det_limit_side_len=640 to KYC engine only.")
else:
    print("  SOME CHECKS FAILED -- do NOT apply. Review failures above.")
print()
