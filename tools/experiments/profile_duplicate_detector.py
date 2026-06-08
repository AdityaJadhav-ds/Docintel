"""
profile_duplicate_detector.py
==============================
Profiles the duplicate detector in full detail:
  - DB query count and timing
  - Image hashing time
  - Hamming distance scan time
  - ID number scan time
  - Complexity (O(1) / O(n) / O(n^2)) assessment
  - Projection at 10 / 50 / 194 / 1000 users

Usage:
    cd backend
    venv\\Scripts\\python.exe profile_duplicate_detector.py
"""
import sys, os, time, logging
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
logging.disable(logging.CRITICAL)

from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document
from app.fraud.image_hashing import compute_all_hashes, hamming_distance

def t(label, fn):
    t0 = time.perf_counter()
    r  = fn()
    ms = int((time.perf_counter() - t0) * 1000)
    print(f"  {label:<50} {ms:>6}ms")
    return r, ms

def section(title): print(f"\n{'='*62}\n{title}\n{'='*62}")

# ── Download real Aadhaar image (doc 31) ──────────────────────────────────────
section("SETUP")
sb = get_supabase()
doc = sb.table("documents").select("*").eq("id", 31).single().execute().data
raw_bytes = _download_document(doc["storage_path"])
print(f"  Downloaded Aadhaar: {len(raw_bytes)} bytes")

# ── 1. Image hashing ──────────────────────────────────────────────────────────
section("1. IMAGE HASHING — compute_all_hashes()")
hashes, hash_ms = t("compute_all_hashes() on Aadhaar image", lambda: compute_all_hashes(raw_bytes))
print(f"\n  Hashes generated: {list(hashes.keys())}")
print(f"  Hash values (first 16 chars):")
for k, v in hashes.items():
    print(f"    {k}: {str(v)[:16]}...")

# ── 2. Fetch all stored hashes ────────────────────────────────────────────────
section("2. DB FETCH — _fetch_all_hashes()")
from app.fraud.duplicate_detector import _fetch_all_hashes

all_hashes, fetch_ms = t("_fetch_all_hashes(exclude_user_id=9)", lambda: _fetch_all_hashes(exclude_user_id=9))
print(f"\n  Rows fetched from image_hashes table: {len(all_hashes)}")
if all_hashes:
    print(f"  Columns per row: {list(all_hashes[0].keys())}")
    # Estimate payload size
    import json
    payload_kb = len(json.dumps(all_hashes)) / 1024
    print(f"  Payload size: ~{payload_kb:.1f} KB")

# ── 3. Hamming distance scan ──────────────────────────────────────────────────
section("3. HAMMING SCAN — O(n) loop over all stored hashes")

from app.fraud.image_hashing import classify_hash_match, similarity_score
from app.fraud.duplicate_detector import find_image_duplicates

n = len(all_hashes)
print(f"  Scanning {n} stored hashes...")

# Time just the scan loop (not the fetch)
def scan_only():
    matches = []
    for stored in all_hashes:
        p_dist = hamming_distance(hashes["phash"], stored.get("phash", ""))
        a_dist = hamming_distance(hashes["ahash"], stored.get("ahash", ""))
        d_dist = hamming_distance(hashes["dhash"], stored.get("dhash", ""))
        min_dist = min(p_dist, a_dist, d_dist)
        if min_dist <= 10:   # HashThreshold.NEAR_DUPLICATE
            matches.append(stored)
    return matches

matches, scan_ms = t(f"Hamming scan over {n} rows", scan_only)
per_row_us = (scan_ms * 1000) / max(n, 1)
print(f"\n  Matches found: {len(matches)}")
print(f"  Time per row: {per_row_us:.1f} microseconds")

# ── 4. ID number scan ─────────────────────────────────────────────────────────
section("4. ID NUMBER SCAN — extracted_data full-table reads")

# Time each of the 2 queries that find_id_duplicates() does
def fetch_all_extracted_aadhaar():
    return (sb.table("extracted_data")
              .select("user_id, doc_type, aadhaar_number")
              .neq("user_id", 9)
              .execute())

def fetch_all_extracted_pan():
    return (sb.table("extracted_data")
              .select("user_id, doc_type, pan_number")
              .neq("user_id", 9)
              .execute())

res_a, aadhaar_q_ms = t("SELECT aadhaar_number FROM extracted_data", fetch_all_extracted_aadhaar)
res_p, pan_q_ms     = t("SELECT pan_number    FROM extracted_data", fetch_all_extracted_pan)

n_rows_a = len(res_a.data or [])
n_rows_p = len(res_p.data or [])
print(f"\n  Rows in extracted_data (aadhaar query): {n_rows_a}")
print(f"  Rows in extracted_data (pan query):     {n_rows_p}")
print(f"  Note: both queries do full-table scan (WHERE user_id != X)")

# ── 5. Store image hash ───────────────────────────────────────────────────────
section("5. STORE HASH — INSERT into image_hashes")
# Dry run — don't actually insert, just time the build
_, build_ms = t("Build hash payload (no insert)", lambda: {
    "user_id": 9, "document_id": 17, "doc_type": "aadhaar",
    "phash": hashes["phash"], "ahash": hashes["ahash"], "dhash": hashes["dhash"],
})
print(f"  (INSERT not executed — read-only profile)")

# ── 6. Full analyze_duplicates() timing ──────────────────────────────────────
section("6. FULL analyze_duplicates() END-TO-END")
from app.fraud.duplicate_detector import analyze_duplicates

_, full_ms = t("analyze_duplicates() complete call",
               lambda: analyze_duplicates(
                   image_input=raw_bytes, user_id=9, doc_type="aadhaar",
                   document_id=17, aadhaar_number="980104884128", pan_number=None,
               ))

# ── 7. Summary and complexity analysis ───────────────────────────────────────
section("7. COMPLEXITY ANALYSIS")

print(f"""
  ALGORITHM BREAKDOWN:
  ┌─────────────────────────────────────────────────────────┐
  │  Step                         Time     Complexity       │
  ├─────────────────────────────────────────────────────────┤
  │  compute_all_hashes()         {hash_ms:>5}ms   O(1)           │
  │  _fetch_all_hashes() DB read  {fetch_ms:>5}ms   O(n) network   │
  │  Hamming scan loop            {scan_ms:>5}ms   O(n) CPU       │
  │  ID aadhaar query             {aadhaar_q_ms:>5}ms   O(n) network   │
  │  ID PAN query                 {pan_q_ms:>5}ms   O(n) network   │
  │  FULL call                    {full_ms:>5}ms   O(n) total     │
  └─────────────────────────────────────────────────────────┘

  Stored hash rows in DB:      {n}
  Extracted data rows in DB:   {n_rows_a}

  VERDICT: O(n) where n = number of users in the system.
  Per document: 3 Supabase round-trips + 1 in-memory scan.
""")

# ── 8. Projection at scale ────────────────────────────────────────────────────
section("8. PROJECTION AT SCALE")

# The dominant costs scale with n (rows fetched from DB, not scan time which is tiny)
# Scan is ~microseconds. DB fetch grows with payload size.
db_fetch_ms   = fetch_ms + aadhaar_q_ms + pan_q_ms
scan_fixed_ms = scan_ms     # in-memory, fast even at scale

# Current state: n=194 users, measuring at ~n hashes and rows
rows_now = max(n, n_rows_a, 1)

print(f"  Current DB rows: ~{rows_now}")
print(f"  Current total time: {full_ms}ms\n")

# Project: DB fetch time scales linearly with rows (network payload)
# Scan scales linearly but is negligible (microseconds per row)
header = f"  {'Users':>8}  {'Hash rows':>10}  {'DB fetch':>10}  {'Scan':>8}  {'Total/doc':>10}"
print(header)
print(f"  {'-'*62}")

for n_users in [10, 50, 194, 500, 1000, 5000]:
    scale = n_users / max(rows_now, 1)
    proj_fetch = int(db_fetch_ms * scale)
    proj_scan  = int(scan_ms * scale)
    proj_total = proj_fetch + proj_scan + hash_ms + build_ms
    marker = " <-- NOW" if abs(n_users - rows_now) < 50 else ""
    print(f"  {n_users:>8}  {n_users*2:>10}  {proj_fetch:>9}ms  {proj_scan:>7}ms  {proj_total:>9}ms{marker}")

print(f"""
  KEY FINDING:
  - The DB fetch (3 Supabase queries that download ALL rows) is O(n)
  - At 194 users it is already ~{full_ms}ms
  - At 1000 users it will be ~{int(full_ms * 1000/max(rows_now,1))}ms per document
  - At 5000 users it will be ~{int(full_ms * 5000/max(rows_now,1))}ms per document
  - This is a confirmed scalability problem (but fine for current 194-user scale)
""")
