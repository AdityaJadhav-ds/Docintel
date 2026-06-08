"""
test_academic_ocr_pipeline.py
==============================
Tests the full academic OCR pipeline by:
1. Finding a real user
2. Uploading a synthetic test image to the upload endpoint
3. Checking the response contains OCR fields
4. Querying list_user_documents to verify fields appear in the API response

Run: python test_academic_ocr_pipeline.py
"""
import os, sys, io, json, time, urllib.request, urllib.parse
sys.path.insert(0, '.')
os.chdir(r'Z:\doc-validator 2\doc-validator\backend')

from dotenv import load_dotenv
load_dotenv('.env')

BASE_URL = "http://127.0.0.1:8000/api"
PASS = []
FAIL = []

def check(label, condition, detail=''):
    if condition:
        print(f'  PASS  {label}')
        PASS.append(label)
    else:
        print(f'  FAIL  {label}: {detail}')
        FAIL.append(label)

def api(method, path, **kwargs):
    url = f"{BASE_URL}{path}"
    if 'data' in kwargs:
        req = urllib.request.Request(url, data=kwargs['data'], method=method)
        if 'headers' in kwargs:
            for k, v in kwargs['headers'].items():
                req.add_header(k, v)
    else:
        req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f'  HTTP {e.code}: {body[:300]}')
        return {'error': e.code, 'body': body}

# ── 1. Get latest user ────────────────────────────────────────────────────────
print('=== Step 1: Get latest user ===')
from supabase import create_client
sb = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_KEY'])
users = sb.table('users').select('id, full_name').order('id', desc=True).limit(1).execute()
if not users.data:
    print('No users — create one first')
    sys.exit(1)
user_id = users.data[0]['id']
print(f'  user_id={user_id} ({users.data[0]["full_name"]})')

# ── 2. Create a synthetic test marksheet image ─────────────────────────────────
print()
print('=== Step 2: Creating synthetic test marksheet image ===')
try:
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np

    img = Image.new('RGB', (800, 600), color='white')
    draw = ImageDraw.Draw(img)

    # Draw fake marksheet content
    lines = [
        'MAHARASHTRA STATE BOARD OF SECONDARY AND HIGHER SECONDARY EDUCATION',
        '',
        'STATEMENT OF MARKS',
        '',
        'Candidate Name: NIKITA BHAGVAN JADHAV',
        'Seat No: 12345678',
        '',
        'MARKS OBTAINED   : 411',
        'MAXIMUM MARKS    : 500',
        '',
        'Percentage        : 82.20',
        '',
        'Result: DISTINCTION',
        '',
        'Examination Year  : March 2020',
    ]

    y = 40
    for line in lines:
        draw.text((40, y), line, fill='black')
        y += 35

    img_bytes = io.BytesIO()
    img.save(img_bytes, format='PNG')
    img_bytes = img_bytes.getvalue()
    print(f'  Created synthetic marksheet: {len(img_bytes)} bytes')
    check('Create test image', True)
except Exception as e:
    print(f'  PIL not available: {e} — using minimal PNG bytes')
    # Minimal 1x1 white PNG
    import struct, zlib
    def minimal_png():
        def pack(fmt, *args): return struct.pack(fmt, *args)
        def chunk(name, data):
            c = name + data
            return pack('>I', len(data)) + c + pack('>I', zlib.crc32(c) & 0xffffffff)
        header = b'\x89PNG\r\n\x1a\n'
        ihdr = chunk(b'IHDR', pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
        idat = chunk(b'IDAT', zlib.compress(b'\x00\xff\xff\xff'))
        iend = chunk(b'IEND', b'')
        return header + ihdr + idat + iend
    img_bytes = minimal_png()
    check('Create minimal PNG', True)

# ── 3. Upload to /api/users/{id}/documents/upload ─────────────────────────────
print()
print('=== Step 3: Upload academic doc via API ===')
import email.mime.multipart
boundary = b'----TestBoundary1234567890'
body  = b'--' + boundary + b'\r\n'
body += b'Content-Disposition: form-data; name="doc_type"\r\n\r\ntenth\r\n'
body += b'--' + boundary + b'\r\n'
body += b'Content-Disposition: form-data; name="file"; filename="test_marksheet.png"\r\n'
body += b'Content-Type: image/png\r\n\r\n'
body += img_bytes + b'\r\n'
body += b'--' + boundary + b'--\r\n'

print(f'  Uploading to POST /api/users/{user_id}/documents/upload ...')
print(f'  (This runs MasterPipeline — may take 10-30s)')
t0 = time.time()

req = urllib.request.Request(
    f'{BASE_URL}/users/{user_id}/documents/upload',
    data=body,
    method='POST',
)
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary.decode()}')

try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        resp_data = json.loads(resp.read())
    elapsed = time.time() - t0
    print(f'  Response in {elapsed:.1f}s:')
    print(f'  {json.dumps(resp_data, indent=4)[:800]}')
    
    doc = resp_data.get('document', {})
    check('Upload succeeded', resp_data.get('success'))
    check('doc_type=tenth', resp_data.get('doc_type') == 'tenth')
    check('storage_path set', bool(resp_data.get('storage_path')))
    check('extracted_percentage present', 'extracted_percentage' in doc,
          f'doc keys: {list(doc.keys())}')
    check('extracted_name present', 'extracted_name' in doc)
    check('ocr_confidence present', 'ocr_confidence' in doc)
    
except urllib.error.HTTPError as e:
    body_err = e.read().decode()
    print(f'  HTTP {e.code}: {body_err[:400]}')
    check('Upload succeeded', False, f'HTTP {e.code}')
except Exception as e:
    print(f'  Error: {e}')
    check('Upload succeeded', False, str(e))

# ── 4. Verify via list_user_documents ─────────────────────────────────────────
print()
print('=== Step 4: Verify via GET /api/users/{id}/documents ===')
time.sleep(1)
docs_resp = api('GET', f'/users/{user_id}/documents')
docs = docs_resp.get('documents', [])
academic_docs = [d for d in docs if d.get('doc_type') in ('tenth', 'twelfth', 'diploma', 'degree', 'semester')]
print(f'  Total docs: {len(docs)}, Academic docs: {len(academic_docs)}')
check('At least 1 academic doc in list', len(academic_docs) > 0)
if academic_docs:
    d = academic_docs[0]
    print(f'  Latest academic doc: {json.dumps({k: v for k, v in d.items() if k != "signed_url"}, indent=4)[:500]}')
    ex = d.get('extracted', {})
    check('extracted.percentage in response', 'percentage' in ex, f'extracted keys: {list(ex.keys())}')
    check('extracted.grade in response', 'grade' in ex)
    check('extracted.name in response', 'name' in ex)
    check('extracted.confidence in response', 'confidence' in ex)

# ── Summary ───────────────────────────────────────────────────────────────────
print()
print('=' * 55)
print(f'RESULTS: {len(PASS)} passed, {len(FAIL)} failed')
if FAIL:
    print(f'FAILED: {FAIL}')
    sys.exit(1)
else:
    print('ALL TESTS PASSED')
    print()
    print('Academic OCR pipeline is now CONNECTED to the database.')
    print('Upload a 10th/12th/Degree doc via the UI to see real OCR results.')
