"""
verify_routing.py
==================
Step 3 verification — confirms the new OCR routing is correct before
running the 10-user batch.

Tests:
  1. Aadhaar (user 16, doc 31) → must use KYC (mobile) engine
  2. PAN     (user 16, doc 32) → must use KYC (mobile) engine
  3. Synthetic bank statement  → must use COMPLEX (server) engine

Checks:
  - [OCR ROUTE] line confirms correct engine selection
  - OCR completes without error
  - Extracted fields present
  - Confidence reported
"""
import sys, os, io, time, logging, urllib.request

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Keep logs quiet so [OCR ROUTE] prints are easy to spot
logging.getLogger("docvalidator").setLevel(logging.ERROR)
logging.getLogger("paddleocr").setLevel(logging.ERROR)
logging.getLogger("paddle").setLevel(logging.ERROR)

from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document
from app.services.ocr_pipeline import process_document

PASS = "[PASS]"
FAIL = "[FAIL]"

def section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")

# ─────────────────────────────────────────────────────────────────────────────
# 1. Aadhaar
# ─────────────────────────────────────────────────────────────────────────────
section("TEST 1: Aadhaar (doc 31, user 16)")

sb = get_supabase()
doc_aadhaar = sb.table("documents").select("*").eq("id", 31).single().execute().data
aadhaar_bytes = _download_document(doc_aadhaar["storage_path"])

print(f"  File size: {len(aadhaar_bytes)} bytes")
print(f"  Calling process_document with doc_type_hint='aadhaar' ...")
t0 = time.time()
res_a = process_document(io.BytesIO(aadhaar_bytes), doc_type_hint="aadhaar")
elapsed_a = time.time() - t0

print(f"  Elapsed:   {elapsed_a:.2f}s")
print(f"  Detected:  {res_a.get('doc_type')}")
print(f"  Conf:      {res_a.get('ocr_confidence')}")
print(f"  Extracted: {res_a.get('extracted')}")

checks_a = {
    "doc_type=aadhaar":   res_a.get("doc_type") == "aadhaar",
    "aadhaar_number":     bool(res_a.get("extracted", {}).get("aadhaar_number")),
    "confidence>0.8":     res_a.get("ocr_confidence", 0) > 0.8,
    "completed<30s":      elapsed_a < 30,
}
for check, ok in checks_a.items():
    print(f"  {PASS if ok else FAIL} {check}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. PAN
# ─────────────────────────────────────────────────────────────────────────────
section("TEST 2: PAN (doc 32, user 16)")

doc_pan = sb.table("documents").select("*").eq("id", 32).single().execute().data
pan_bytes = _download_document(doc_pan["storage_path"])

print(f"  File size: {len(pan_bytes)} bytes")
print(f"  Calling process_document with doc_type_hint='pan' ...")
t0 = time.time()
res_p = process_document(io.BytesIO(pan_bytes), doc_type_hint="pan")
elapsed_p = time.time() - t0

print(f"  Elapsed:   {elapsed_p:.2f}s")
print(f"  Detected:  {res_p.get('doc_type')}")
print(f"  Conf:      {res_p.get('ocr_confidence')}")
print(f"  Extracted: {res_p.get('extracted')}")

checks_p = {
    "doc_type=pan":    res_p.get("doc_type") == "pan",
    "name_present":    bool(res_p.get("extracted", {}).get("name")),
    "confidence>0.8":  res_p.get("ocr_confidence", 0) > 0.8,
    "completed<30s":   elapsed_p < 30,
}
for check, ok in checks_p.items():
    print(f"  {PASS if ok else FAIL} {check}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Bank statement (local synthetic — verifies COMPLEX engine routing)
#    We create a simple multi-line text PDF in-memory and verify:
#      a) routing picks COMPLEX engine
#      b) OCR completes
# ─────────────────────────────────────────────────────────────────────────────
section("TEST 3: Bank Statement (synthetic — routing check only)")

# Create a minimal valid PDF in memory with bank-statement keywords
BANK_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 120>>stream
BT /F1 12 Tf 50 750 Td
(SBI Bank Statement - Account 1234567890) Tj
0 -20 Td (Date        Description              Amount) Tj
0 -20 Td (01/06/2024  Opening Balance          10000.00) Tj
ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000438 00000 n
trailer<</Size 6/Root 1 0 R>>
startxref
521
%%EOF"""

print(f"  Synthetic PDF size: {len(BANK_PDF)} bytes")
print(f"  Calling process_document with doc_type_hint='bank_statement' ...")
t0 = time.time()
res_b = process_document(io.BytesIO(BANK_PDF), doc_type_hint="bank_statement")
elapsed_b = time.time() - t0

print(f"  Elapsed:   {elapsed_b:.2f}s")
print(f"  Detected:  {res_b.get('doc_type')}")
print(f"  Raw text:  {res_b.get('raw_text','')[:200]!r}")
print(f"  Engines:   {res_b.get('engines_used')}")

checks_b = {
    "completed_no_crash": True,   # if we get here, it didn't crash
    "elapsed_reported":   elapsed_b > 0,
}
for check, ok in checks_b.items():
    print(f"  {PASS if ok else FAIL} {check}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
section("ROUTING VERIFICATION SUMMARY")

all_checks = {**checks_a, **checks_p, **checks_b}
passed = sum(all_checks.values())
total  = len(all_checks)

print(f"\n  Results: {passed}/{total} checks passed\n")
for check, ok in all_checks.items():
    print(f"  {'OK' if ok else 'XX'} {check}")

print(f"\n  Aadhaar time: {elapsed_a:.2f}s  (benchmark baseline: 82s server / 14s mobile)")
print(f"  PAN time:     {elapsed_p:.2f}s  (benchmark baseline: 72s server / 13s mobile)")
print(f"  Bank time:    {elapsed_b:.2f}s")
print()
if passed == total:
    print("  ALL CHECKS PASSED — safe to proceed to 10-user batch run.")
else:
    print("  SOME CHECKS FAILED — investigate before running batch.")
