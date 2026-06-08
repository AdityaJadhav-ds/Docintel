import ast, pathlib, sys
files = [
    'app/academic_engine/layout_v2/zone_segmenter.py',
    'app/academic_engine/layout_v2/summary_locator.py',
    'app/academic_engine/preprocessing/document_restoration.py',
]
ok = True
for f in files:
    try:
        ast.parse(pathlib.Path(f).read_text(encoding='utf-8'))
        name = pathlib.Path(f).name
        print('OK ', name)
    except SyntaxError as e:
        name = pathlib.Path(f).name
        print('ERR', name, str(e))
        ok = False
sys.exit(0 if ok else 1)
