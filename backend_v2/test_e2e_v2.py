import urllib.request, json, sys, os, time

# Find test PDF
test_pdf = None
for d in ['test_documents', '../input_documents', '..']:
    if os.path.isdir(d):
        for fname in os.listdir(d):
            if fname.lower().endswith('.pdf'):
                test_pdf = os.path.join(d, fname)
                break
    if test_pdf:
        break

if not test_pdf:
    print('No PDF found in any test directory')
    sys.exit(1)

print('Using PDF:', test_pdf)

# Upload
boundary = 'BOUNDARY12345'
with open(test_pdf, 'rb') as f:
    pdf_bytes = f.read()

body = (
    b'--' + boundary.encode() + b'\r\n'
    b'Content-Disposition: form-data; name="file"; filename="test.pdf"\r\n'
    b'Content-Type: application/pdf\r\n\r\n'
    + pdf_bytes + b'\r\n'
    b'--' + boundary.encode() + b'--\r\n'
)
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/ocr/pipeline/start',
    data=body,
    headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
)
resp = json.loads(urllib.request.urlopen(req).read())
run_id = resp['run_id']
print('Run ID:', run_id)

# Wait for result
time.sleep(6)
result_resp = json.loads(urllib.request.urlopen(
    f'http://127.0.0.1:8000/api/ocr/pipeline/result/{run_id}'
).read())
result = result_resp['result']

print()
print('=== PIPELINE RESULT SUMMARY ===')
print('pipeline   :', result.get('pipeline'))
print('word_count :', result.get('word_count'))
print('regions    :', result.get('metadata', {}).get('region_types', {}))
print()

blocks = result.get('blocks', [])
print(f'Total blocks: {len(blocks)}')
for i, b in enumerate(blocks):
    rtype  = b.get('type')
    raw    = b.get('raw_lines', [])
    first  = raw[0] if raw else '(none)'
    print(f'  Block {i}: type={rtype}  first_line={repr(first[:80])}')

    if rtype == 'table':
        grid = b.get('rows', [])
        ncol = b.get('col_count', 0)
        print(f'    Table: {ncol} cols x {len(grid)} rows')
        for row in grid[:4]:
            print(f'      {row}')

    elif rtype == 'kv_block':
        for pair in b.get('pairs', [])[:5]:
            print(f'    KV  {pair["key"]} : {pair["value"]}')

    elif rtype in ('header', 'paragraph', 'footer'):
        text = b.get('text', '')
        print(f'    text: {repr(text[:120])}')

print()
print('raw_lines present in all blocks:', all('raw_lines' in b for b in blocks))
