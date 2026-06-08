import urllib.request, json
resp = urllib.request.urlopen('http://127.0.0.1:8000/api/users/165/documents', timeout=15)
data = json.loads(resp.read())
docs = data.get('documents', [])
academic = [d for d in docs if d.get('doc_type') in ('tenth','twelfth','diploma','degree','semester')]
print('Total docs:', len(docs))
print('Academic docs:', len(academic))
for d in academic[:2]:
    print('  doc_type:', d.get('doc_type'))
    print('  ocr_confidence:', d.get('ocr_confidence'))
    ex = d.get('extracted', {})
    print('  extracted:', ex)
    print()
