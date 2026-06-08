"""
inspect_fetch_user.py
======================
Investigates why _fetch_user() takes 4.1s per user.

Checks:
  1. Is get_supabase() creating a new client each call? (should be singleton)
  2. How long is the actual SELECT query?
  3. How many round trips does process_user_documents() make to Supabase total?
  4. Is the 4.1s a connection overhead or a slow query?
  5. Does the second call to the same user cost the same?

Usage:
    cd backend
    venv\\Scripts\\python.exe inspect_fetch_user.py
"""
import sys, os, time, logging
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from app.core.supabase_client import get_supabase

TARGET_USER = 9

def t(label, fn):
    t0 = time.perf_counter()
    result = fn()
    ms = int((time.perf_counter() - t0) * 1000)
    print(f"  {label:<45} {ms:>6}ms")
    return result, ms

def section(title): print(f"\n{'='*62}\n{title}\n{'='*62}")

# ─────────────────────────────────────────────────────────────────────────────
section("1. Supabase client identity — is it a singleton?")
sb1 = get_supabase()
sb2 = get_supabase()
same = sb1 is sb2
print(f"  get_supabase() call 1 id: {id(sb1)}")
print(f"  get_supabase() call 2 id: {id(sb2)}")
print(f"  Same object (singleton):  {same}")
if not same:
    print("  WARNING: get_supabase() is returning a NEW client each call!")

# ─────────────────────────────────────────────────────────────────────────────
section("2. Raw query timings — 5 consecutive fetches")
sb = get_supabase()

for i in range(5):
    _, ms = t(f"  SELECT users WHERE id={TARGET_USER}  (run {i+1})",
              lambda: sb.table("users").select("*").eq("id", TARGET_USER).single().execute())

# ─────────────────────────────────────────────────────────────────────────────
section("3. Is it SELECT * or does the users table have many columns?")
row, _ = t("  Fetch user row", lambda: sb.table("users").select("*").eq("id", TARGET_USER).single().execute())
if row.data:
    cols = list(row.data.keys())
    print(f"\n  Columns in users table ({len(cols)} total): {cols}")
    sizes = {k: len(str(v)) for k, v in row.data.items()}
    print(f"  Approximate row size: {sum(sizes.values())} bytes")

# ─────────────────────────────────────────────────────────────────────────────
section("4. Count ALL Supabase round trips in process_user_documents()")
print("""
  Tracing all get_supabase() calls by monkey-patching:
""")

call_log = []
original_get = get_supabase.__wrapped__ if hasattr(get_supabase, '__wrapped__') else None

import app.core.supabase_client as _sc
import app.services.validation_service as _vs

original_get_supabase = _sc.get_supabase

call_count = [0]
def counting_get_supabase():
    call_count[0] += 1
    return original_get_supabase()

_sc.get_supabase = counting_get_supabase

# Patch all the places that call get_supabase
import app.services.ocr_pipeline as _ocr
_ocr_orig = _ocr.get_supabase if hasattr(_ocr, 'get_supabase') else None

# Re-import to pick up patches
call_count[0] = 0
from app.services.validation_service import _fetch_user, _fetch_documents

call_count[0] = 0
t("  _fetch_user()", lambda: _fetch_user(TARGET_USER))
after_fetch_user = call_count[0]
print(f"  get_supabase() calls in _fetch_user:    {after_fetch_user}")

call_count[0] = 0
t("  _fetch_documents()", lambda: _fetch_documents(TARGET_USER))
after_fetch_docs = call_count[0]
print(f"  get_supabase() calls in _fetch_documents: {after_fetch_docs}")

_sc.get_supabase = original_get_supabase  # restore

# ─────────────────────────────────────────────────────────────────────────────
section("5. Timing variance — is 4.1s consistent or a one-off cold hit?")
sb = get_supabase()
times = []
for i in range(6):
    t0 = time.perf_counter()
    sb.table("users").select("id,full_name").eq("id", TARGET_USER).single().execute()
    ms = int((time.perf_counter() - t0) * 1000)
    times.append(ms)
    print(f"  Run {i+1}: {ms}ms")

print(f"\n  Min: {min(times)}ms   Max: {max(times)}ms   Avg: {sum(times)//len(times)}ms")

# ─────────────────────────────────────────────────────────────────────────────
section("6. Does fetch_user SELECT * when only a few fields are needed?")
_, ms_star  = t("  SELECT *       (all columns)", lambda: sb.table("users").select("*").eq("id", TARGET_USER).single().execute())
_, ms_slim  = t("  SELECT id,full_name (slim select)", lambda: sb.table("users").select("id,full_name").eq("id", TARGET_USER).single().execute())

print(f"\n  Difference: {ms_star - ms_slim}ms  ({'slim faster' if ms_slim < ms_star else 'star faster / same'})")

# ─────────────────────────────────────────────────────────────────────────────
section("7. Could we batch-load all 10 users at once?")
batch_users = [7, 29, 107, 2, 3, 4, 5, 6, 8, 9]
_, ms_batch = t("  SELECT WHERE id IN (10 users)", lambda: sb.table("users").select("*").in_("id", batch_users).execute())
_, ms_single = t("  SELECT WHERE id = one user   ", lambda: sb.table("users").select("*").eq("id", 9).single().execute())

batch_per_user = ms_batch // len(batch_users)
print(f"\n  Batch 10 users:        {ms_batch}ms  ({batch_per_user}ms effective per user)")
print(f"  Single user query:     {ms_single}ms")
print(f"  Batch saves per user:  {ms_single - batch_per_user}ms")

# ─────────────────────────────────────────────────────────────────────────────
section("CONCLUSIONS")
avg_q = sum(times) // len(times)
print(f"  Singleton:         {'YES' if same else 'NO - THIS IS THE BUG'}")
print(f"  Avg SELECT time:   {avg_q}ms  (cold={times[0]}ms  warm={min(times[1:])}ms)")
print(f"  Columns fetched:   {len(cols) if row.data else '?'} (SELECT *)")
print(f"  Batch vs single:   {ms_batch}ms / 10 = {batch_per_user}ms/user (vs {ms_single}ms single)")
print()
if avg_q > 1000:
    print("  DIAGNOSIS: Supabase query latency is consistently high (>1s).")
    print("  This is likely geographic network latency to the Supabase region.")
    print("  Fix: pre-fetch all user records in a single batch query before the loop.")
elif times[0] > 2000 and min(times[1:]) < 500:
    print("  DIAGNOSIS: First call is cold (connection setup), subsequent calls are fast.")
    print("  Fix: warm the Supabase connection at startup / reuse connection.")
else:
    print("  DIAGNOSIS: Query latency is within normal range.")
