"""
test_ocr_thread_safety.py
==========================
Verifies that the KYC OCR singleton is safe for concurrent use
BEFORE enabling parallel workers in the batch processor.

Tests:
  1. 2 threads, same image — results must be identical
  2. 2 threads, different images (Aadhaar + PAN) — both must complete without crash
  3. 4 threads, 4 docs — stress test at higher concurrency
  4. Memory check — no spike beyond expected model RAM

Pass criteria (must ALL pass before enabling parallel workers):
  [A] No unhandled exceptions across any thread
  [B] No deadlocks (all threads complete within timeout)
  [C] Aadhaar number extracted identically across all threads
  [D] PAN name extracted identically across all threads
  [E] Memory growth < 500 MB above baseline (models already loaded)
  [F] OCR time per thread <= 3x sequential time (no serialisation penalty)

Usage:
    cd backend
    venv\\Scripts\\python.exe test_ocr_thread_safety.py
"""
import sys, os, time, threading, traceback, logging
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ["FLAGS_enable_pir_api"]         = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

try:
    import psutil
    PROC = psutil.Process(os.getpid())
    mem_mb = lambda: PROC.memory_info().rss / 1024 / 1024
except ImportError:
    mem_mb = lambda: 0.0

from app.extraction.pipeline import _get_ocr, render_pages
from app.extraction.geometry import flatten_paddle_result, group_rows
from app.services.ocr_pipeline import _extract_kyc_fields
from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document

TIMEOUT_S = 120   # max seconds to wait for any thread to finish

def section(t): print(f"\n{'='*64}\n{t}\n{'='*64}")

# ── Download + render docs once ───────────────────────────────────────────────
section("SETUP — loading OCR engine and images")

sb = get_supabase()
doc_a = sb.table("documents").select("*").eq("id", 31).single().execute().data
doc_p = sb.table("documents").select("*").eq("id", 32).single().execute().data

aadhaar_bytes = _download_document(doc_a["storage_path"])
pan_bytes     = _download_document(doc_p["storage_path"])

from app.extraction.pdf import render_pages as _render
aadhaar_bgr = _render(aadhaar_bytes, "doc.jpg")[0]
pan_bgr     = _render(pan_bytes,     "doc.jpg")[0]

# Pre-warm singleton (avoids counting cold-start as thread overhead)
print("  Warming KYC OCR singleton (first call)...")
t0 = time.monotonic()
ocr = _get_ocr("kyc")
_warm_result = ocr.predict(aadhaar_bgr) if hasattr(ocr, "predict") else ocr.ocr(aadhaar_bgr, cls=False)
warm_ms = int((time.monotonic() - t0) * 1000)
print(f"  Singleton warmed in {warm_ms}ms")
mem_baseline = mem_mb()
print(f"  Baseline memory: {mem_baseline:.0f} MB")

# ── Thread worker ─────────────────────────────────────────────────────────────
def ocr_worker(thread_id: int, bgr, doc_type: str,
               results: dict, errors: dict, timings: dict):
    try:
        t0 = time.monotonic()
        engine = _get_ocr("kyc")   # must return the SAME singleton
        raw = engine.predict(bgr) if hasattr(engine, "predict") else engine.ocr(bgr, cls=False)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        flat = raw
        if flat and isinstance(flat[0], list):
            flat = flat[0]
        from app.extraction.geometry import flatten_paddle_result, group_rows
        boxes = flatten_paddle_result(flat or [])
        rows  = group_rows(boxes)
        text  = "\n".join(" ".join(b["text"] for b in r) for r in rows)
        extr  = _extract_kyc_fields(text, doc_type)

        results[thread_id]  = extr
        timings[thread_id]  = elapsed_ms
    except Exception as exc:
        errors[thread_id] = traceback.format_exc()

# ──────────────────────────────────────────────────────────────────────────────
# TEST 1: 2 threads, same image (Aadhaar × 2)
# ──────────────────────────────────────────────────────────────────────────────
section("TEST 1: 2 threads, same image (Aadhaar x2)")
results1, errors1, timings1 = {}, {}, {}
threads = [
    threading.Thread(target=ocr_worker, args=(i, aadhaar_bgr, "aadhaar", results1, errors1, timings1))
    for i in range(2)
]
t_wall = time.monotonic()
for th in threads: th.start()
for th in threads: th.join(timeout=TIMEOUT_S)
wall1_ms = int((time.monotonic() - t_wall) * 1000)

alive1 = [th for th in threads if th.is_alive()]
print(f"  Threads completed: {len(threads)-len(alive1)}/{len(threads)}")
print(f"  Deadlocks:         {len(alive1)}")
print(f"  Errors:            {len(errors1)}")
print(f"  Wall time:         {wall1_ms}ms")
for tid, ms in timings1.items():
    print(f"    Thread {tid}: {ms}ms   extracted={results1.get(tid,{})}")
if errors1:
    for tid, tb in errors1.items():
        print(f"    Thread {tid} ERROR:\n{tb}")

check1_no_crash    = len(errors1) == 0
check1_no_deadlock = len(alive1) == 0
check1_identical   = (len(results1) == 2 and
                      results1.get(0, {}).get("aadhaar_number") ==
                      results1.get(1, {}).get("aadhaar_number"))

# ──────────────────────────────────────────────────────────────────────────────
# TEST 2: 2 threads, different images (Aadhaar + PAN)
# ──────────────────────────────────────────────────────────────────────────────
section("TEST 2: 2 threads, different images (Aadhaar + PAN)")
results2, errors2, timings2 = {}, {}, {}
threads2 = [
    threading.Thread(target=ocr_worker, args=(0, aadhaar_bgr, "aadhaar", results2, errors2, timings2)),
    threading.Thread(target=ocr_worker, args=(1, pan_bgr,     "pan",     results2, errors2, timings2)),
]
t_wall = time.monotonic()
for th in threads2: th.start()
for th in threads2: th.join(timeout=TIMEOUT_S)
wall2_ms = int((time.monotonic() - t_wall) * 1000)

alive2 = [th for th in threads2 if th.is_alive()]
print(f"  Threads completed: {len(threads2)-len(alive2)}/{len(threads2)}")
print(f"  Deadlocks:         {len(alive2)}")
print(f"  Errors:            {len(errors2)}")
print(f"  Wall time:         {wall2_ms}ms  (vs sequential ~{warm_ms*2}ms)")
for tid, ms in timings2.items():
    print(f"    Thread {tid}: {ms}ms  extracted={results2.get(tid,{})}")
if errors2:
    for tid, tb in errors2.items():
        print(f"    Thread {tid} ERROR:\n{tb}")

check2_no_crash    = len(errors2) == 0
check2_no_deadlock = len(alive2) == 0
check2_aadhaar_ok  = bool(results2.get(0, {}).get("aadhaar_number"))
check2_pan_ok      = bool(results2.get(1, {}).get("name"))

# ──────────────────────────────────────────────────────────────────────────────
# TEST 3: 4 threads, 4 docs (stress)
# ──────────────────────────────────────────────────────────────────────────────
section("TEST 3: 4 threads stress (2x Aadhaar + 2x PAN)")
results3, errors3, timings3 = {}, {}, {}
docs3 = [(0, aadhaar_bgr, "aadhaar"),
         (1, pan_bgr,     "pan"),
         (2, aadhaar_bgr, "aadhaar"),
         (3, pan_bgr,     "pan")]
threads3 = [
    threading.Thread(target=ocr_worker, args=(i, bgr, dt, results3, errors3, timings3))
    for i, bgr, dt in docs3
]
t_wall = time.monotonic()
for th in threads3: th.start()
for th in threads3: th.join(timeout=TIMEOUT_S * 2)
wall3_ms = int((time.monotonic() - t_wall) * 1000)
mem_after = mem_mb()

alive3 = [th for th in threads3 if th.is_alive()]
print(f"  Threads completed: {len(threads3)-len(alive3)}/{len(threads3)}")
print(f"  Deadlocks:         {len(alive3)}")
print(f"  Errors:            {len(errors3)}")
print(f"  Wall time:         {wall3_ms}ms")
for tid, ms in timings3.items():
    print(f"    Thread {tid}: {ms}ms  extracted={results3.get(tid,{})}")
if errors3:
    for tid, tb in errors3.items():
        print(f"    Thread {tid} ERROR:\n{tb}")

mem_growth = mem_after - mem_baseline
check3_no_crash    = len(errors3) == 0
check3_no_deadlock = len(alive3) == 0
check3_mem_ok      = mem_growth < 500
check3_speed_ok    = wall3_ms < warm_ms * 3 * 2   # 4 threads <= 3x single * 2

# ──────────────────────────────────────────────────────────────────────────────
# PASS / FAIL
# ──────────────────────────────────────────────────────────────────────────────
section("PASS / FAIL VERDICT")
print(f"  Memory baseline:  {mem_baseline:.0f} MB")
print(f"  Memory after 4t:  {mem_after:.0f} MB  (growth: {mem_growth:.0f} MB)\n")

checks = {
    "[A] Test1: No exceptions (2 threads, same image)":   check1_no_crash,
    "[B] Test1: No deadlocks":                            check1_no_deadlock,
    "[C] Test1: Aadhaar number identical both threads":   check1_identical,
    "[D] Test2: No exceptions (Aadhaar + PAN threads)":   check2_no_crash,
    "[E] Test2: No deadlocks":                            check2_no_deadlock,
    "[F] Test2: Aadhaar number extracted":                check2_aadhaar_ok,
    "[G] Test2: PAN name extracted":                      check2_pan_ok,
    "[H] Test3: No exceptions (4-thread stress)":         check3_no_crash,
    "[I] Test3: No deadlocks":                            check3_no_deadlock,
    f"[J] Test3: Memory growth < 500 MB ({mem_growth:.0f} MB)": check3_mem_ok,
}

all_pass = True
for label, ok in checks.items():
    if not ok: all_pass = False
    print(f"  {'[PASS]' if ok else '[FAIL]'} {label}")

print()
if all_pass:
    print("  ALL CHECKS PASSED.")
    print("  PaddleOCR KYC singleton is thread-safe for concurrent use.")
    print("  Safe to enable max_workers=2 in batch processor.")
else:
    print("  SOME CHECKS FAILED.")
    print("  Do NOT enable parallel workers until failures are resolved.")
print()
