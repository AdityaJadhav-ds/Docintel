"""Quick end-to-end pipeline self-test — synthetic marksheet image."""
import sys, numpy as np, cv2

# Create a synthetic marksheet image with readable text
img = np.ones((1200, 900, 3), dtype=np.uint8) * 255
font = cv2.FONT_HERSHEY_SIMPLEX
cv2.putText(img, 'MAHARASHTRA STATE BOARD', (50, 80),  font, 1.2, (0,0,0), 2)
cv2.putText(img, 'HIGHER SECONDARY CERTIFICATE EXAMINATION', (50, 140), font, 0.7, (0,0,0), 2)
cv2.putText(img, 'MARCH - 2023', (50, 200), font, 0.9, (0,0,0), 2)
cv2.putText(img, 'Student Name: RAHUL SHARMA PATIL', (50, 300), font, 0.8, (0,0,0), 2)
cv2.putText(img, 'Seat No: 1234567', (50, 360), font, 0.8, (0,0,0), 2)
cv2.putText(img, 'Percentage: 75.17', (50, 900), font, 1.0, (0,0,0), 2)
cv2.putText(img, 'Result: PASS', (50, 960), font, 1.0, (0,0,0), 2)
cv2.putText(img, 'Class: FIRST CLASS', (50, 1020), font, 0.9, (0,0,0), 2)
_, buf = cv2.imencode('.jpg', img)
img_bytes = buf.tobytes()

sys.path.insert(0, '.')
from app.academic_engine.pipeline.academic_pipeline import run_pipeline

result = run_pipeline(img_bytes, hint='hsc')
meta   = result.get('_meta', {})

print('=== PIPELINE SELF-TEST ===')
print('  doc_type  :', result.get('document_type'))
print('  name      :', result.get('candidate_name'))
print('  board     :', result.get('board_university'))
print('  year      :', result.get('passing_year'))
print('  percentage:', result.get('percentage'))
print('  result    :', result.get('result'))
print('  status    :', meta.get('status'))
print('  engine    :', meta.get('extraction_engine'))
print('  warnings  :', meta.get('warnings', []))
print('=== DONE ===')

# Exit non-zero if nothing was extracted
fields = [result.get(f) for f in ('document_type', 'percentage', 'result')]
ok = any(f and f not in ('Unknown Document', None) for f in fields)
sys.exit(0 if ok else 1)
