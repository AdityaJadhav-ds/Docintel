"""
test_synth.py - Synthetic bank statement E2E test for v2 pipeline.
"""
import urllib.request, json, sys, os, time, io

# --------------------------------------------------------------------------
# Build a minimal valid PDF manually (no external deps)
# --------------------------------------------------------------------------
def make_pdf():
    content = b"""BT
/F1 12 Tf
50 800 Td (STATEMENT OF ACCOUNT) Tj
50 778 Td (Name: Shridhan Sanjay Shinde) Tj
50 756 Td (Branch Code : 8234) Tj
50 734 Td (IFSC Code : KKBK0002046) Tj
50 712 Td (Account No : 8850687756) Tj
50 680 Td (Date Description Debit Credit Balance) Tj
50 658 Td (02Feb UPI/Shridhan 66.00 4445) Tj
50 636 Td (03Feb NEFT TRANSFER 500.00 3945) Tj
50 614 Td (04Feb ATM WITHDRAWAL 2000.00 1945) Tj
ET"""
    obj4 = b"4 0 obj<</Length " + str(len(content)).encode() + b">>\nstream\n" + content + b"\nendstream\nendobj\n"
    
    obj1 = b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    obj2 = b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    obj3 = b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    obj5 = b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"

    body = b"%PDF-1.4\n" + obj1 + obj2 + obj3 + obj4 + obj5
    offsets = []
    pos = body.index(obj1)
    offsets.append(pos)
    pos = body.index(obj2)
    offsets.append(pos)
    pos = body.index(obj3)
    offsets.append(pos)
    pos = body.index(obj4[:10])
    offsets.append(pos)
    pos = body.index(obj5)
    offsets.append(pos)

    xref_pos = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for o in offsets:
        xref += ("%010d 00000 n \n" % o).encode()
    trailer = (
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF\n"
    )
    return body + xref + trailer


pdf_bytes = make_pdf()
print(f"PDF size: {len(pdf_bytes)} bytes")

# --------------------------------------------------------------------------
# Upload to pipeline
# --------------------------------------------------------------------------
boundary = b"BOUNDARY_V2_TEST"
body_parts = (
    b"--" + boundary + b"\r\n"
    b'Content-Disposition: form-data; name="file"; filename="synth_bank.pdf"\r\n'
    b"Content-Type: application/pdf\r\n\r\n"
    + pdf_bytes
    + b"\r\n--" + boundary + b"--\r\n"
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/ocr/pipeline/start",
    data=body_parts,
    headers={"Content-Type": "multipart/form-data; boundary=" + boundary.decode()},
)
resp = json.loads(urllib.request.urlopen(req).read())
run_id = resp["run_id"]
print("Run ID:", run_id)

# --------------------------------------------------------------------------
# Wait and fetch result
# --------------------------------------------------------------------------
time.sleep(10)
result_resp = json.loads(urllib.request.urlopen(
    f"http://127.0.0.1:8000/api/ocr/pipeline/result/{run_id}"
).read())
result = result_resp["result"]

print()
print("=== PIPELINE RESULT ===")
print("pipeline    :", result.get("pipeline"))
print("word_count  :", result.get("word_count"))
print("region_types:", result.get("metadata", {}).get("region_types", {}))
print()

blocks = result.get("blocks", [])
print(f"Total blocks: {len(blocks)}")
for i, b in enumerate(blocks):
    rtype = b.get("type")
    raw   = b.get("raw_lines", [])
    print(f"\n  [{i}] type={rtype}  raw_lines={len(raw)}")
    if rtype == "table":
        grid = b.get("rows", [])
        print(f"       {b.get('col_count')} cols x {len(grid)} rows")
        for row in grid[:6]:
            print(f"       {row}")
    elif rtype == "kv_block":
        for p in b.get("pairs", [])[:6]:
            print(f"       KV: {p['key']} : {p['value']}")
    else:
        print(f"       {repr(b.get('text', '')[:120])}")

print()
missing = [i for i, b in enumerate(blocks) if "raw_lines" not in b]
if missing:
    print("FAIL - blocks missing raw_lines:", missing)
else:
    print("raw_lines present in all blocks: OK")

print()
print("clean_text preview:")
print(result.get("clean_text", "")[:400])
