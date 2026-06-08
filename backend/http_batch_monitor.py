"""
http_batch_monitor.py
======================
Tests the real 2-worker batch system via HTTP — no Paddle imports,
no process conflicts.

Flow:
  1. POST /api/ocr/bulk?force=true  → triggers background batch
  2. GET  /api/ocr/bulk/status      → poll every 5s until done
  3. Print live progress + final timing

This is the REAL production test: uses the backend's existing
_ocr_semaphore(2) + BATCH_SIZE=3 + _OCR_PREDICT_LOCK in pipeline.py.

Usage:
    cd backend
    venv\\Scripts\\python.exe http_batch_monitor.py
"""
import sys, time, json
sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
except ImportError:
    print("requests not found — trying urllib")
    import urllib.request, urllib.error
    class _R:
        def __init__(self, data, code):
            self._d = data; self.status_code = code
        def json(self): return self._d
        def raise_for_status(self):
            if self.status_code >= 400: raise Exception(f"HTTP {self.status_code}")
    class requests:
        @staticmethod
        def get(url, timeout=10):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as r:
                    return _R(json.loads(r.read()), r.status)
            except Exception as e: raise
        @staticmethod
        def post(url, timeout=10):
            req = urllib.request.Request(url, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return _R(json.loads(r.read()), r.status)
            except Exception as e: raise

BASE = "http://127.0.0.1:8000/api"
POLL_INTERVAL = 5   # seconds between status polls

def section(t): print(f"\n{'='*62}\n{t}\n{'='*62}")

# ── 1. Verify backend is up ───────────────────────────────────────────────────
section("1. HEALTH CHECK")
try:
    h = requests.get(f"{BASE}/health", timeout=5)
    hj = h.json()
    print(f"  status:      {hj.get('status')}")
    print(f"  supabase:    {hj.get('supabase')}")
    print(f"  workers:     {hj.get('workers')}")
    print(f"  queue_depth: {hj.get('queue_depth')}")
except Exception as e:
    print(f"  Backend not responding: {e}")
    sys.exit(1)

# ── 2. Check nothing is already running ───────────────────────────────────────
section("2. PRE-RUN STATUS")
try:
    st = requests.get(f"{BASE}/ocr/bulk/status", timeout=5).json()
    print(f"  running:   {st.get('running')}")
    print(f"  processed: {st.get('processed')}")
    print(f"  total:     {st.get('total')}")
    if st.get("running"):
        print("  WARNING: A batch is already running. Attaching to existing run...")
except Exception as e:
    print(f"  Could not get status: {e}")

# ── 3. Trigger batch ──────────────────────────────────────────────────────────
section("3. TRIGGERING BATCH  (force=true)")
t_start = time.monotonic()
try:
    resp = requests.post(f"{BASE}/ocr/bulk?force=true", timeout=10)
    rj   = resp.json()
    print(f"  success:      {rj.get('success')}")
    print(f"  jobs_queued:  {rj.get('jobs_queued')}")
    print(f"  total_users:  {rj.get('total_users')}")
    print(f"  message:      {rj.get('message')}")
    if rj.get("already_running"):
        print("  (already running — attaching to existing run)")
except Exception as e:
    print(f"  Trigger failed: {e}")
    sys.exit(1)

# ── 4. Poll until complete ────────────────────────────────────────────────────
section("4. LIVE PROGRESS")
print(f"  {'Elapsed':>8}  {'Processed':>10}  {'Success':>8}  {'Failed':>7}  {'Skipped':>8}  {'%':>6}  Last user")
print(f"  {'-'*65}")

last_processed = 0
stall_count    = 0

while True:
    time.sleep(POLL_INTERVAL)
    try:
        st = requests.get(f"{BASE}/ocr/bulk/status", timeout=5).json()
    except Exception as e:
        print(f"  [poll error: {e}]")
        continue

    elapsed   = int(time.monotonic() - t_start)
    processed = st.get("processed", 0)
    total     = st.get("total", 1)
    success   = st.get("success", 0)
    failed    = st.get("failed", 0)
    skipped   = st.get("skipped", 0)
    pct       = st.get("percent_complete", 0)
    cur_user  = st.get("current_user", "-")
    running   = st.get("running", True)

    print(f"  {elapsed:>7}s  {processed:>10}  {success:>8}  {failed:>7}  {skipped:>8}  {pct:>5.1f}%  user={cur_user}")

    # Stall detection
    if processed == last_processed:
        stall_count += 1
        if stall_count >= 12:   # 60s with no progress
            print(f"\n  WARNING: No progress for {stall_count * POLL_INTERVAL}s — possible stall")
    else:
        stall_count = 0
    last_processed = processed

    if not running:
        break

# ── 5. Final report ───────────────────────────────────────────────────────────
wall_s = time.monotonic() - t_start
section("5. FINAL REPORT")

total_done = success + failed
errors     = st.get("errors", [])

print(f"  Total wall time:     {wall_s:.1f}s  ({wall_s/60:.1f} min)")
print(f"  Users attempted:     {total}")
print(f"  Processed:           {processed}")
print(f"  Succeeded:           {success}")
print(f"  Failed:              {failed}")
print(f"  Skipped:             {skipped}")
if total_done > 0:
    avg_s = (wall_s - (skipped * 0.1)) / max(total_done, 1)
    print(f"  Avg per user:        {avg_s:.1f}s")
    print(f"  Throughput:          {60/avg_s:.2f} users/min")

    # Project 194 users
    proj_s = int(194 * avg_s)
    print(f"\n  194-user projection: {proj_s}s = {proj_s//60} min {proj_s%60}s")

if errors:
    print(f"\n  Errors ({len(errors)}):")
    for e in errors[:10]:
        print(f"    user={e.get('user_id')}  elapsed={e.get('elapsed_sec')}s  {str(e.get('error',''))[:80]}")

section("DONE")
