"""
bench_rec_batch.py
===================
Benchmarks text_recognition_batch_size across [1, 8, 16, 20, 32]
on the same Aadhaar and PAN images.

Goal: find if batching all 20 recognition passes together is faster
      than serial/small-batch recognition on CPU.

Usage:
    cd backend
    venv\\Scripts\\python.exe bench_rec_batch.py
"""
import sys, os, io, time, logging
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ["FLAGS_enable_pir_api"]         = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from paddleocr import PaddleOCR
from app.extraction.pdf import render_pages
from app.extraction.geometry import flatten_paddle_result, group_rows
from app.services.ocr_pipeline import _extract_kyc_fields
from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document

# ── Batch sizes to test (default for PaddleOCR 3.x is 6) ────────────────────
BATCH_SIZES   = [1, 6, 8, 16, 20, 32]   # 6 = estimated default
BASE_PARAMS   = dict(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
    text_detection_model_name="PP-OCRv3_mobile_det",
    text_recognition_model_name="en_PP-OCRv5_mobile_rec",
)

def section(t): print(f"\n{'='*64}\n{t}\n{'='*64}")
def hline():    print(f"  {'-'*62}")

# ── Download and render once ──────────────────────────────────────────────────
section("SETUP — downloading and rendering images")
sb = get_supabase()
doc_a = sb.table("documents").select("*").eq("id", 31).single().execute().data
doc_p = sb.table("documents").select("*").eq("id", 32).single().execute().data

aadhaar_bytes = _download_document(doc_a["storage_path"])
pan_bytes     = _download_document(doc_p["storage_path"])

aadhaar_bgr = render_pages(aadhaar_bytes, "doc.jpg")[0]
pan_bgr     = render_pages(pan_bytes,     "doc.jpg")[0]

h_a, w_a = aadhaar_bgr.shape[:2]
h_p, w_p = pan_bgr.shape[:2]
print(f"  Aadhaar: {len(aadhaar_bytes)}B  {w_a}x{h_a}px")
print(f"  PAN:     {len(pan_bytes)}B  {w_p}x{h_p}px")

# ── OCR runner ────────────────────────────────────────────────────────────────
def run_ocr(engine, bgr, doc_type):
    t0 = time.monotonic()
    raw = engine.predict(bgr) if hasattr(engine, "predict") else engine.ocr(bgr, cls=False)
    ocr_ms = int((time.monotonic() - t0) * 1000)

    flat = raw
    if flat and isinstance(flat[0], list):
        flat = flat[0]
    boxes = flatten_paddle_result(flat or [])
    rows  = group_rows(boxes)
    text  = "\n".join(" ".join(b["text"] for b in r) for r in rows)
    conf  = round(sum(b.get("confidence", 0) for b in boxes) / len(boxes), 3) if boxes else 0.0
    extr  = _extract_kyc_fields(text, doc_type)

    return {"ocr_ms": ocr_ms, "confidence": conf, "extracted": extr, "boxes": len(boxes)}

# ── Run all batch sizes ───────────────────────────────────────────────────────
section("RUNNING BENCHMARKS")
results = {}

for bs in BATCH_SIZES:
    label = f"batch={bs}" + (" [est. default]" if bs == 6 else "")
    print(f"\n  Initializing OCR with text_recognition_batch_size={bs} ...")
    engine = PaddleOCR(**BASE_PARAMS, text_recognition_batch_size=bs)

    print(f"  Running Aadhaar ... ", end="", flush=True)
    r_a = run_ocr(engine, aadhaar_bgr, "aadhaar")
    print(f"{r_a['ocr_ms']}ms")

    print(f"  Running PAN ...     ", end="", flush=True)
    r_p = run_ocr(engine, pan_bgr, "pan")
    print(f"{r_p['ocr_ms']}ms")

    results[bs] = {"aadhaar": r_a, "pan": r_p}

# ── Comparison table ──────────────────────────────────────────────────────────
section("COMPARISON TABLE")

baseline_a_ms = results[6]["aadhaar"]["ocr_ms"]
baseline_p_ms = results[6]["pan"]["ocr_ms"]

print(f"\n  {'batch_size':<14} {'Aadhaar ms':>12} {'vs default':>10} {'PAN ms':>10} {'vs default':>10} {'avg conf':>10}")
hline()

best_bs   = None
best_avg  = float("inf")

for bs in BATCH_SIZES:
    r_a = results[bs]["aadhaar"]
    r_p = results[bs]["pan"]
    avg_ms = (r_a["ocr_ms"] + r_p["ocr_ms"]) / 2

    d_a = f"{(r_a['ocr_ms'] - baseline_a_ms) / baseline_a_ms * 100:+.1f}%"
    d_p = f"{(r_p['ocr_ms'] - baseline_p_ms) / baseline_p_ms * 100:+.1f}%"

    avg_conf = round((r_a["confidence"] + r_p["confidence"]) / 2, 3)
    default_mark = " <-- default" if bs == 6 else ""
    print(f"  {bs:<14} {r_a['ocr_ms']:>12}ms {d_a:>10} {r_p['ocr_ms']:>10}ms {d_p:>10} {avg_conf:>10}{default_mark}")

    if avg_ms < best_avg:
        best_avg = avg_ms
        best_bs  = bs

print(f"\n  Best batch size by avg OCR time: {best_bs} ({best_avg:.0f}ms avg)")

# ── Field comparison (all vs batch=6 baseline) ────────────────────────────────
section("EXTRACTION ACCURACY vs BASELINE (batch=6)")
baseline_a_extr = results[6]["aadhaar"]["extracted"]
baseline_p_extr = results[6]["pan"]["extracted"]

for bs in BATCH_SIZES:
    if bs == 6:
        continue
    r_a = results[bs]["aadhaar"]["extracted"]
    r_p = results[bs]["pan"]["extracted"]
    aa_match = all(r_a.get(k) == baseline_a_extr.get(k) for k in set(r_a)|set(baseline_a_extr))
    pa_match = all(r_p.get(k) == baseline_p_extr.get(k) for k in set(r_p)|set(baseline_p_extr))
    status = "IDENTICAL" if (aa_match and pa_match) else "DIFFERENT"
    print(f"  batch={bs:<4}  Aadhaar={'MATCH' if aa_match else 'DIFF'}  PAN={'MATCH' if pa_match else 'DIFF'}  -> {status}")
    if not aa_match:
        for k in set(r_a)|set(baseline_a_extr):
            if r_a.get(k) != baseline_a_extr.get(k):
                print(f"    Aadhaar.{k}: {baseline_a_extr.get(k)!r} -> {r_a.get(k)!r}")
    if not pa_match:
        for k in set(r_p)|set(baseline_p_extr):
            if r_p.get(k) != baseline_p_extr.get(k):
                print(f"    PAN.{k}: {baseline_p_extr.get(k)!r} -> {r_p.get(k)!r}")

# ── Pass/fail verdict for best batch size ─────────────────────────────────────
section(f"PASS / FAIL VERDICT  (best batch_size={best_bs} vs default batch=6)")

r_a = results[best_bs]["aadhaar"]
r_p = results[best_bs]["pan"]
b_a = results[6]["aadhaar"]
b_p = results[6]["pan"]

speedup_a   = (b_a["ocr_ms"] - r_a["ocr_ms"]) / b_a["ocr_ms"] * 100
speedup_p   = (b_p["ocr_ms"] - r_p["ocr_ms"]) / b_p["ocr_ms"] * 100
conf_drop_a = (b_a["confidence"] - r_a["confidence"]) / b_a["confidence"] * 100
conf_drop_p = (b_p["confidence"] - r_p["confidence"]) / b_p["confidence"] * 100

aa_match = all(r_a["extracted"].get(k) == b_a["extracted"].get(k)
               for k in set(r_a["extracted"])|set(b_a["extracted"]))
pa_match = all(r_p["extracted"].get(k) == b_p["extracted"].get(k)
               for k in set(r_p["extracted"])|set(b_p["extracted"]))

checks = {
    f"Aadhaar speedup >= 15%  ({speedup_a:+.1f}%)":   speedup_a >= 15,
    f"PAN speedup >= 15%      ({speedup_p:+.1f}%)":   speedup_p >= 15,
    f"Aadhaar fields identical":                        aa_match,
    f"PAN fields identical":                            pa_match,
    f"Aadhaar conf drop <= 2% ({conf_drop_a:.1f}%)":  conf_drop_a <= 2,
    f"PAN conf drop <= 2%     ({conf_drop_p:.1f}%)":  conf_drop_p <= 2,
}

all_pass = True
for label, ok in checks.items():
    if not ok: all_pass = False
    print(f"  {'[PASS]' if ok else '[FAIL]'} {label}")

print()
if all_pass:
    print(f"  ALL PASSED -- safe to apply text_recognition_batch_size={best_bs} to KYC engine only.")
else:
    print(f"  SOME FAILED -- do not apply. Consider next alternative.")
print()
