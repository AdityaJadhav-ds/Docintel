"""
bench_ocr_lock.py
==================
Benchmarks "2 workers + OCR predict lock" vs sequential processing.

Runs process_user_documents() for 2 real users:
  - SEQUENTIAL:  user A finishes completely, then user B starts
  - PARALLEL:    both users start simultaneously; only predict() is serialized

All non-OCR work runs freely in parallel:
  - Downloads (Supabase Storage)
  - Supabase DB reads/writes
  - Review engine
  - Fraud analysis dispatch

Expected gain:
  - While User A is doing OCR, User B downloads docs
  - While User A saves results, User B is waiting for the OCR lock
  - Net: ~30-40% throughput gain without multiprocessing or RAM cost

Pass criteria:
  [A] Both users complete successfully (no crash)
  [B] Wall time (parallel) < sequential * 0.80  (>=20% improvement)
  [C] Aadhaar numbers unchanged vs sequential baseline
  [D] Memory growth < 100 MB above sequential baseline

Usage:
    cd backend
    venv\\Scripts\\python.exe bench_ocr_lock.py
"""
import sys, os, time, threading, logging
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

from app.services.validation_service import process_user_documents

# Users 2 and 3 were stable in the previous 10-user batch (both had Aadhaar + PAN)
USER_A = 2
USER_B = 3

def section(t): print(f"\n{'='*64}\n{t}\n{'='*64}")

# ── Pre-warm OCR engine (exclude from timing) ─────────────────────────────────
section("SETUP — warming OCR engine")
print("  Processing a throwaway call to warm the KYC singleton...")
t0 = time.monotonic()
_ = process_user_documents(USER_A)
warm_ms = int((time.monotonic() - t0) * 1000)
print(f"  Warm-up done in {warm_ms}ms")

# ── Sequential baseline ───────────────────────────────────────────────────────
section("SEQUENTIAL BASELINE (user A then user B)")
mem_seq_start = mem_mb()

t0 = time.monotonic()
res_seq_a = process_user_documents(USER_A)
time_seq_a = int((time.monotonic() - t0) * 1000)

t1 = time.monotonic()
res_seq_b = process_user_documents(USER_B)
time_seq_b = int((time.monotonic() - t1) * 1000)

time_seq_total = int((time.monotonic() - t0) * 1000)
mem_seq_end = mem_mb()

print(f"  User A ({USER_A}): {time_seq_a}ms")
print(f"  User B ({USER_B}): {time_seq_b}ms")
print(f"  TOTAL sequential: {time_seq_total}ms ({time_seq_total/1000:.1f}s)")
print(f"  Memory: {mem_seq_start:.0f} MB -> {mem_seq_end:.0f} MB")

# Capture baseline field values
def get_aadhaar(result):
    for r in (result.get("results") or []):
        if r.get("doc_type") == "aadhaar":
            return (r.get("extracted_data") or {}).get("aadhaar_number")
    return None

baseline_aadhaar_a = get_aadhaar(res_seq_a)
baseline_aadhaar_b = get_aadhaar(res_seq_b)
print(f"  Baseline Aadhaar A: {baseline_aadhaar_a}")
print(f"  Baseline Aadhaar B: {baseline_aadhaar_b}")

# ── Parallel (2 threads + OCR lock) ──────────────────────────────────────────
section("PARALLEL — 2 threads + OCR predict lock")
print("  _OCR_PREDICT_LOCK is active in pipeline.py")
print(f"  Starting both users simultaneously...")

results_par = {}
errors_par  = {}
timings_par = {}

def run_user(uid, slot):
    try:
        t0 = time.monotonic()
        res = process_user_documents(uid)
        timings_par[slot] = int((time.monotonic() - t0) * 1000)
        results_par[slot] = res
    except Exception as e:
        import traceback
        errors_par[slot] = traceback.format_exc()

mem_par_start = mem_mb()
t_wall = time.monotonic()

th_a = threading.Thread(target=run_user, args=(USER_A, "a"))
th_b = threading.Thread(target=run_user, args=(USER_B, "b"))
th_a.start()
th_b.start()
th_a.join(timeout=300)
th_b.join(timeout=300)

time_par_wall = int((time.monotonic() - t_wall) * 1000)
mem_par_end = mem_mb()

print(f"  User A ({USER_A}): {timings_par.get('a', '?')}ms")
print(f"  User B ({USER_B}): {timings_par.get('b', '?')}ms")
print(f"  TOTAL wall time:  {time_par_wall}ms ({time_par_wall/1000:.1f}s)")
print(f"  Memory: {mem_par_start:.0f} MB -> {mem_par_end:.0f} MB (growth: {mem_par_end-mem_par_start:.0f} MB)")

if errors_par:
    for slot, tb in errors_par.items():
        print(f"  ERROR in thread {slot}:\n{tb}")

par_aadhaar_a = get_aadhaar(results_par.get("a", {}))
par_aadhaar_b = get_aadhaar(results_par.get("b", {}))
print(f"  Parallel Aadhaar A: {par_aadhaar_a}")
print(f"  Parallel Aadhaar B: {par_aadhaar_b}")

# ── Results ───────────────────────────────────────────────────────────────────
section("COMPARISON")
improvement_pct = (time_seq_total - time_par_wall) / time_seq_total * 100
speedup = time_seq_total / max(time_par_wall, 1)
effective_per_user = time_par_wall / 2

print(f"""
  {'Metric':<35} {'Sequential':>14} {'2-worker+lock':>14}
  {'-'*65}
  {'Total wall time':<35} {time_seq_total:>13}ms {time_par_wall:>13}ms
  {'Effective time per user':<35} {time_seq_total//2:>13}ms {effective_per_user:>13.0f}ms
  {'Speedup':<35} {'1.0x':>14} {speedup:>13.2f}x
  {'Improvement':<35} {'0%':>14} {improvement_pct:>13.1f}%
  {'Memory growth':<35} {'0 MB':>14} {mem_par_end-mem_seq_end:>13.0f} MB
""")

proj_seq  = 194 * (time_seq_total // 2) // 1000
proj_par  = int(194 * effective_per_user // 1000)
print(f"  194-user projection (sequential): {proj_seq}s = {proj_seq//60} min")
print(f"  194-user projection (2-worker):   {proj_par}s = {proj_par//60} min")

# ── Pass / Fail ───────────────────────────────────────────────────────────────
section("PASS / FAIL VERDICT")

no_crash      = len(errors_par) == 0 and not th_a.is_alive() and not th_b.is_alive()
speed_ok      = improvement_pct >= 20
aadhaar_a_ok  = par_aadhaar_a == baseline_aadhaar_a if baseline_aadhaar_a else True
aadhaar_b_ok  = par_aadhaar_b == baseline_aadhaar_b if baseline_aadhaar_b else True
mem_ok        = (mem_par_end - mem_seq_end) < 100

checks = {
    f"[A] No crashes or deadlocks":                                  no_crash,
    f"[B] Wall time improvement >= 20%  ({improvement_pct:.1f}%)":  speed_ok,
    f"[C] Aadhaar A unchanged  ({par_aadhaar_a})":                  aadhaar_a_ok,
    f"[D] Aadhaar B unchanged  ({par_aadhaar_b})":                  aadhaar_b_ok,
    f"[E] Memory growth < 100 MB  ({mem_par_end-mem_seq_end:.0f} MB)": mem_ok,
}

all_pass = True
for label, ok in checks.items():
    if not ok: all_pass = False
    print(f"  {'[PASS]' if ok else '[FAIL]'} {label}")

print()
if all_pass:
    print("  ALL PASSED — 2-worker + OCR lock approach is safe and effective.")
    print("  Safe to enable ThreadPoolExecutor(max_workers=2) in batch processor.")
else:
    print("  SOME FAILED — review before enabling parallel workers.")
print()
