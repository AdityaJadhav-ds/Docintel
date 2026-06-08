"""
batch_50_monitor.py
====================
Runs process_user_documents() for 50 users sequentially through the
batch_10_monitor-style timer, measuring:

  - Time per user
  - Total wall time
  - Memory growth
  - Disconnect events
  - OCR errors
  - Stale text (verified on user 2 as canary)

The backend uses MAX_WORKERS=2 + _OCR_PREDICT_LOCK, so this measures
real concurrent throughput via the API queue, not the raw function.

Usage:
    cd backend
    venv\\Scripts\\python.exe batch_50_monitor.py
"""
import sys, os, time, requests, psutil, logging
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from app.services.validation_service import process_user_documents
from app.core.supabase_client import get_supabase

PROC = psutil.Process(os.getpid())

def mem_mb(): return PROC.memory_info().rss / 1024 / 1024
def section(t): print(f"\n{'='*62}\n{t}\n{'='*62}")

# ── Fetch first 50 user IDs ────────────────────────────────────────────────────
section("SETUP")
sb = get_supabase()
res = sb.table("users").select("id").order("id").limit(50).execute()
user_ids = [r["id"] for r in (res.data or [])]
print(f"  Users to process: {len(user_ids)}")
print(f"  User IDs: {user_ids[:10]}...{user_ids[-5:]}")

# ── Stale text pre-snapshot (user 2 as canary) ────────────────────────────────
canary_id = 2
pre_rows = (
    sb.table("extracted_data")
    .select("doc_type, aadhaar_number, confidence_score, processed_at")
    .eq("user_id", canary_id)
    .execute()
    .data or []
)

section("BATCH PROCESSING — 50 users (2-worker + OCR lock)")
mem_start = mem_mb()
t_wall_start = time.monotonic()

results = []
print(f"\n  {'User':<8} {'Status':<15} {'Time(s)':>8}   {'Docs':>5}   {'Notes'}")
print(f"  {'-'*60}")

ocr_errors = 0
disconnect_events = 0

for uid in user_ids:
    t0 = time.monotonic()
    try:
        result = process_user_documents(uid)
        elapsed = time.monotonic() - t0
        status  = result.get("overall_status", "UNKNOWN")
        docs    = len(result.get("results", []))
        results.append({"user_id": uid, "elapsed": elapsed, "status": status, "docs": docs, "ok": True})
        print(f"  {uid:<8} {status:<15} {elapsed:>8.1f}   {docs:>5}   ")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        err_str = str(exc)[:60]
        if "disconnect" in err_str.lower() or "offline" in err_str.lower():
            disconnect_events += 1
        if "ocr" in err_str.lower() or "paddle" in err_str.lower():
            ocr_errors += 1
        results.append({"user_id": uid, "elapsed": elapsed, "status": "ERROR", "docs": 0, "ok": False})
        print(f"  {uid:<8} {'ERROR':<15} {elapsed:>8.1f}   {'0':>5}   {err_str}")

wall_total = time.monotonic() - t_wall_start
mem_end = mem_mb()

# ── Summary ───────────────────────────────────────────────────────────────────
section("BATCH SUMMARY")
succeeded  = sum(1 for r in results if r["ok"])
failed     = len(results) - succeeded
total_docs = sum(r["docs"] for r in results)
times      = [r["elapsed"] for r in results if r["ok"]]
avg_time   = sum(times) / len(times) if times else 0
min_time   = min(times) if times else 0
max_time   = max(times) if times else 0

print(f"  Users attempted:    {len(user_ids)}")
print(f"  Users succeeded:    {succeeded}")
print(f"  Users failed:       {failed}")
print(f"  OCR errors:         {ocr_errors}")
print(f"  Disconnect events:  {disconnect_events}")
print(f"  Total docs:         {total_docs}")
print(f"  Total wall time:    {wall_total:.1f}s  ({wall_total/60:.1f} min)")
print(f"  Avg per user:       {avg_time:.1f}s")
print(f"  Min per user:       {min_time:.1f}s")
print(f"  Max per user:       {max_time:.1f}s")
print(f"  Users/minute:       {60/avg_time:.2f}" if avg_time > 0 else "")
print(f"  Memory start:       {mem_start:.0f} MB")
print(f"  Memory end:         {mem_end:.0f} MB")
print(f"  Memory growth:      {mem_end-mem_start:.0f} MB")

proj_194 = int(194 * avg_time)
print(f"\n  194-user projection: {proj_194}s = {proj_194//60} min  (sequential through this same API)")

# ── Stale text check ──────────────────────────────────────────────────────────
section(f"STALE TEXT VERIFICATION — user {canary_id}")
post_rows = (
    sb.table("extracted_data")
    .select("doc_type, aadhaar_number, confidence_score, processed_at")
    .eq("user_id", canary_id)
    .execute()
    .data or []
)

pre_map  = {r["doc_type"]: r for r in pre_rows}
post_map = {r["doc_type"]: r for r in post_rows}

stale_ok = True
for dt in set(list(pre_map) + list(post_map)):
    pre  = pre_map.get(dt, {})
    post = post_map.get(dt, {})
    ts_changed = pre.get("processed_at") != post.get("processed_at")
    print(f"  {dt}: processed_at {'UPDATED' if ts_changed else 'UNCHANGED'}")
    if not ts_changed:
        stale_ok = False

print(f"  Stale text check: {'PASS' if stale_ok else 'WARN - timestamps not updated'}")

# ── Per-user timing table ─────────────────────────────────────────────────────
section("PER-USER TIMING")
print(f"  {'User':<8} {'Time(s)':>8}    {'Docs':>5}  Status")
for r in results:
    print(f"  {r['user_id']:<8} {r['elapsed']:>8.1f}    {r['docs']:>5}  {r['status']}")

section("DONE")
