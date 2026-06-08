"""
batch_10_monitor.py
====================
Runs OCR on exactly 10 users (3 new + 7 re-runs) and reports:
  - Per-user timing
  - Records per minute
  - Memory usage
  - Supabase update verification
  - Offline/disconnect events (connection errors)
  - Stale text refresh check on one already-processed user

Usage:
    cd backend
    venv\\Scripts\\python.exe batch_10_monitor.py
"""
import sys, os, time, io, gc, traceback
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import logging
logging.getLogger("docvalidator").setLevel(logging.WARNING)
logging.getLogger("paddleocr").setLevel(logging.ERROR)
logging.getLogger("paddle").setLevel(logging.ERROR)

try:
    import psutil
    PROC = psutil.Process(os.getpid())
    def mem_mb():
        return PROC.memory_info().rss / 1024 / 1024
except ImportError:
    def mem_mb():
        return 0.0

from app.core.supabase_client import get_supabase
from app.services.validation_service import process_user_documents

# ── Batch configuration ───────────────────────────────────────────────────────
BATCH_USERS   = [7, 29, 107, 2, 3, 4, 5, 6, 8, 9]   # 3 new + 7 re-runs
RERUN_TARGET  = 2                                       # stale-text check

def sep(title=""):
    if title:
        print(f"\n{'='*60}\n{title}\n{'='*60}")
    else:
        print("-" * 60)

# ── Capture pre-run extracted_data snapshot for re-run target ─────────────────
def snapshot_extracted(sb, user_id):
    cols = "user_id,doc_type,name,aadhaar_number,pan_number,dob,confidence_score,processed_at"
    rows = sb.table("extracted_data").select(cols).eq("user_id", user_id).execute().data or []
    return {r["doc_type"]: r for r in rows}

sep("PRE-RUN STATE")
sb = get_supabase()
pre_snapshot = snapshot_extracted(sb, RERUN_TARGET)
print(f"User {RERUN_TARGET} existing extracted_text (first 100 chars per doc):")
if pre_snapshot:
    for dt, txt in pre_snapshot.items():
        print(f"  {dt}: {str(txt)[:100]!r}")
else:
    print("  (no existing data)")

# ── Run the batch ─────────────────────────────────────────────────────────────
sep(f"BATCH RUN — {len(BATCH_USERS)} users")

results       = []
errors        = []
disconnects   = 0
start_wall    = time.time()
mem_start     = mem_mb()

print(f"{'User':<8} {'Status':<15} {'Time(s)':<10} {'Docs':<6} {'Mem(MB)':<10}")
print("-" * 52)

for uid in BATCH_USERS:
    t0  = time.time()
    mem_before = mem_mb()
    try:
        result = process_user_documents(uid)
        elapsed = time.time() - t0
        mem_after = mem_mb()

        status   = result.get("overall_status", "unknown")
        n_docs   = result.get("total_docs", 0)
        err_msg  = result.get("error", "")

        if "connection" in str(err_msg).lower() or "offline" in str(err_msg).lower():
            disconnects += 1
            status = "DISCONNECT"

        results.append({
            "user_id": uid,
            "elapsed": elapsed,
            "status":  status,
            "docs":    n_docs,
            "mem_mb":  mem_after,
        })
        print(f"{uid:<8} {status:<15} {elapsed:<10.1f} {n_docs:<6} {mem_after:<10.0f}")

    except Exception as exc:
        elapsed = time.time() - t0
        tb = traceback.format_exc()
        if "connection" in str(exc).lower() or "network" in str(exc).lower():
            disconnects += 1
        errors.append({"user_id": uid, "error": str(exc), "elapsed": elapsed})
        print(f"{uid:<8} {'CRASH':<15} {elapsed:<10.1f} {'?':<6} {mem_mb():<10.0f}")
        print(f"  ERROR: {exc}")

    gc.collect()   # encourage Python GC between users

total_wall = time.time() - start_wall
mem_end    = mem_mb()

# ── Summary ───────────────────────────────────────────────────────────────────
sep("BATCH SUMMARY")

done_results = [r for r in results if r["status"] not in ("CRASH",)]
total_docs   = sum(r["docs"] for r in done_results)
avg_per_user = total_wall / len(BATCH_USERS)
recs_per_min = (len(done_results) / total_wall) * 60 if total_wall > 0 else 0
docs_per_min = (total_docs / total_wall) * 60 if total_wall > 0 else 0

print(f"  Users attempted:    {len(BATCH_USERS)}")
print(f"  Users succeeded:    {len(done_results)}")
print(f"  Users crashed:      {len(errors)}")
print(f"  Disconnect events:  {disconnects}")
print(f"  Total docs:         {total_docs}")
print(f"  Total wall time:    {total_wall:.1f}s  ({total_wall/60:.1f} min)")
print(f"  Avg per user:       {avg_per_user:.1f}s")
print(f"  Users/minute:       {recs_per_min:.2f}")
print(f"  Docs/minute:        {docs_per_min:.2f}")
print(f"  Memory start:       {mem_start:.0f} MB")
print(f"  Memory end:         {mem_end:.0f} MB")
print(f"  Memory growth:      {mem_end - mem_start:.0f} MB")

# ── Per-user timing table ─────────────────────────────────────────────────────
sep("PER-USER TIMING")
print(f"{'User':<8} {'Time(s)':<10} {'Docs':<6} {'Status'}")
for r in results:
    print(f"  {r['user_id']:<6} {r['elapsed']:<10.1f} {r['docs']:<6} {r['status']}")
for e in errors:
    print(f"  {e['user_id']:<6} {e['elapsed']:<10.1f} {'?':<6} CRASH: {e['error'][:60]}")

# ── Stale text refresh verification ──────────────────────────────────────────
sep(f"STALE TEXT VERIFICATION — user {RERUN_TARGET}")

sb2 = get_supabase()
post_snapshot = snapshot_extracted(sb2, RERUN_TARGET)

if not pre_snapshot and not post_snapshot:
    print("  No data before or after — user had no documents extracted.")
elif not pre_snapshot:
    print("  NEW extraction (no pre-run data existed).")
    for dt, txt in post_snapshot.items():
        print(f"  {dt}: {str(txt)[:100]!r}")
else:
    print("  Comparing pre vs post extracted data:")
    all_types = set(pre_snapshot) | set(post_snapshot)
    any_changed = False
    for dt in sorted(all_types):
        pre  = pre_snapshot.get(dt, {})
        post = post_snapshot.get(dt, {})
        pre_at  = pre.get("processed_at", "")
        post_at = post.get("processed_at", "")
        time_changed = pre_at != post_at
        any_changed = any_changed or time_changed
        marker = "[UPDATED]" if time_changed else "[UNCHANGED]"
        print(f"  {dt} {marker}")
        for field in ("name", "aadhaar_number", "pan_number", "dob", "confidence_score"):
            pv = str(pre.get(field, ""))
            nv = str(post.get(field, ""))
            changed = pv != nv
            status = "CHANGED" if changed else "same"
            print(f"    {field:<20} {status}  {pv[:40]!r} -> {nv[:40]!r}")
        print(f"    processed_at: {pre_at} -> {post_at}")
    if any_changed:
        print("  PASS: extracted_data rows were re-written — stale text is replaced.")
    else:
        print("  NOTE: processed_at unchanged — OCR may have been skipped or result is identical.")

sep("DONE")
