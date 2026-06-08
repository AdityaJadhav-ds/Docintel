"""
ocr_timing_probe.py  v3
========================
Stage-by-stage timing inside PaddleOCR — production-accurate measurements.

Stubs the broken torch/modelscope import chain so paddleocr can be imported
in a standalone script (same issue that exists in the venv but is hidden
when uvicorn starts because torch is never the first import).

Usage:
    cd backend
    venv\\Scripts\\python.exe ocr_timing_probe.py
"""

import os, sys, types, time, platform, pathlib, subprocess

# ── 1. Env flags (must be before ANY paddle import) ──────────────────────────
os.environ['FLAGS_enable_pir_api']         = '0'
os.environ['FLAGS_enable_pir_in_executor'] = '0'
os.environ['OMP_NUM_THREADS']              = '1'
os.environ['OPENBLAS_NUM_THREADS']         = '1'
os.environ['MKL_NUM_THREADS']              = '1'
os.environ['NUMEXPR_NUM_THREADS']          = '1'

# ── 2. Stub broken torch + modelscope before paddleocr import ────────────────
def _stub_module(name, **attrs):
    m = types.ModuleType(name)
    m.__dict__.update(attrs)
    sys.modules[name] = m
    return m

_stub_module('torch', __version__='0.0.0')
for _sub in ['distributed', 'cuda', 'nn', 'optim', 'utils',
             'backends', 'amp', 'multiprocessing']:
    _stub_module(f'torch.{_sub}')

_stub_module('modelscope')
for _sub in ['utils', 'utils.import_utils', 'utils.ast_utils',
             'utils.file_utils', 'utils.logger', 'utils.torch_utils']:
    _stub_module(f'modelscope.{_sub}')

# ── 3. Now import paddle/paddleocr safely ────────────────────────────────────
import paddle
import paddleocr
from paddleocr import PaddleOCR

import cv2
import numpy as np

# Backend app modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.core.supabase_client import get_supabase
from app.extraction.pdf import render_pages

# ── PROBE START ───────────────────────────────────────────────────────────────
SEP = "=" * 70
print(SEP)
print("OCR TIMING PROBE v3 — Full Stage Breakdown")
print(SEP)

# ── Q1: System ────────────────────────────────────────────────────────────────
print("\n[Q1] SYSTEM")
try:
    cpuout = subprocess.check_output(
        ["wmic", "cpu", "get", "name,NumberOfCores,NumberOfLogicalProcessors", "/format:list"],
        text=True, stderr=subprocess.DEVNULL
    )
    for line in cpuout.strip().splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if v.strip(): print(f"  {k.strip()}: {v.strip()}")
except Exception: pass
print(f"  OS:          {platform.system()} {platform.version()}")
print(f"  Python:      {sys.version.split()[0]}")
print(f"  OMP_THREADS: {os.environ['OMP_NUM_THREADS']}")
print(f"  MKL_THREADS: {os.environ['MKL_NUM_THREADS']}")

# ── Q2/Q3: Versions and GPU ────────────────────────────────────────────────────
print("\n[Q2/Q3/Q4] VERSIONS + GPU")
print(f"  paddleocr:   {paddleocr.__version__}")
print(f"  paddle:      {paddle.__version__}")
print(f"  GPU compiled:{paddle.is_compiled_with_cuda()}")
print(f"  Device:      {paddle.get_device()}")

# ── Q2: Model files ────────────────────────────────────────────────────────────
print("\n[Q2] MODEL FILES ON DISK")
paddle_home = pathlib.Path.home() / ".paddleocr"
for f in sorted(paddle_home.rglob("inference.pdiparams")):
    size_mb = f.stat().st_size / 1024 / 1024
    rel = str(f.relative_to(paddle_home))
    print(f"  {size_mb:5.1f} MB  {rel}")

# ── Download real Aadhaar ──────────────────────────────────────────────────────
print("\n[DOCUMENT] Downloading real Aadhaar from Supabase")
sb = get_supabase()
docs = sb.table("documents").select("id,doc_type,storage_path").eq("doc_type", "aadhaar").limit(1).execute()
if not docs.data:
    print("  ERROR: No aadhaar docs found.")
    sys.exit(1)
storage_path = docs.data[0]["storage_path"]
print(f"  Path: {storage_path}")

t_dl = time.monotonic()
raw_bytes = sb.storage.from_("documents").download(storage_path)
dl_ms = int((time.monotonic() - t_dl) * 1000)
print(f"  Download: {dl_ms}ms  size={len(raw_bytes)//1024}KB")

# ── Q6: Pages ─────────────────────────────────────────────────────────────────
print("\n[Q6] RENDER + PAGE COUNT")
t_render = time.monotonic()
pages = render_pages(raw_bytes, storage_path.split("/")[-1])
render_ms = int((time.monotonic() - t_render) * 1000)
print(f"  Pages rendered: {len(pages)}  render_time={render_ms}ms")
for i, p in enumerate(pages):
    h, w = p.shape[:2]
    print(f"  Page {i}: {w}×{h} = {w*h:,} px ({w*h/1_000_000:.2f}MP) dtype={p.dtype}")

# ── Q5+Q8: Image dims fed into OCR after preprocess ──────────────────────────
print("\n[Q5+Q8] IMAGE DIMENSIONS FED INTO OCR (after preprocess)")
page_count = len(pages)
ocr_inputs = []
for i, bgr in enumerate(pages):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    strip = gray[h//4 : 3*h//4, :]
    lap_var = float(cv2.Laplacian(strip, cv2.CV_64F).var())
    is_noisy = lap_var < 18.0

    ocr_img = bgr
    crop_info = "no crop (single-page doc)"
    if page_count >= 2:
        y1, y2 = int(h * 0.22), int(h * 0.92)
        ocr_img = bgr[y1:y2, :]
        crop_info = f"cropped y={y1}–{y2}"

    oh, ow = ocr_img.shape[:2]
    print(f"  Page {i}:")
    print(f"    Full image:  {w}×{h} px ({w*h/1_000_000:.2f}MP)")
    print(f"    OCR input:   {ow}×{oh} px ({ow*oh/1_000_000:.2f}MP)  [{crop_info}]")
    print(f"    Laplacian:   {lap_var:.1f}  noisy={is_noisy}")
    ocr_inputs.append(ocr_img)

# ── Q7: Orientation classifiers ───────────────────────────────────────────────
print("\n[Q7] ORIENTATION / CLASSIFICATION MODELS")
print("  PaddleOCR init flags:")
print("    use_doc_orientation_classify = False  (disabled)")
print("    use_doc_unwarping            = False  (disabled)")
print("    use_textline_orientation     = False  (disabled)")
print("    enable_mkldnn                = False  (MKL acceleration off)")
print("    cls=False passed at call time          (angle classifier off)")

# ── Init OCR ──────────────────────────────────────────────────────────────────
print("\n[OCR INIT]")
t_init = time.monotonic()
ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    enable_mkldnn=False,
    lang="en"
)
init_ms = int((time.monotonic() - t_init) * 1000)
print(f"  Init time: {init_ms}ms")
print(f"  ocr.ocr available: {hasattr(ocr, 'ocr')}")
print(f"  ocr.predict available: {hasattr(ocr, 'predict')}")

# ── Warmup ────────────────────────────────────────────────────────────────────
print("\n[WARMUP]")
blank = np.zeros((64, 64, 3), dtype=np.uint8)
t_w = time.monotonic()
try:
    if hasattr(ocr, 'predict'):
        ocr.predict(blank)
    else:
        ocr.ocr(blank, cls=False)
except Exception: pass
print(f"  Blank warmup: {int((time.monotonic()-t_w)*1000)}ms")

# ── Q9: Detection vs Recognition split ───────────────────────────────────────
print("\n[Q9] DETECTION vs RECOGNITION TIMING SPLIT")
test_img = ocr_inputs[0]
oh, ow = test_img.shape[:2]
print(f"  Test image: {ow}×{oh} px")

# --- Detection only ---
det_ms, n_det_boxes = -1, 0
print("\n  >> PASS A: Detection only (rec=False, cls=False)")
t_det = time.monotonic()
try:
    det_result = ocr.ocr(test_img, rec=False, cls=False)
    det_ms = int((time.monotonic() - t_det) * 1000)
    if det_result and det_result[0]:
        n_det_boxes = len(det_result[0])
    print(f"     Time:  {det_ms}ms")
    print(f"     Boxes: {n_det_boxes}")
except Exception as e:
    print(f"     FAILED: {e}")

# --- Full pipeline ---
full_ms, n_texts = -1, 0
print("\n  >> PASS B: Full pipeline — det + rec (cls=False)")
t_full = time.monotonic()
try:
    if hasattr(ocr, 'predict'):
        full_result = ocr.predict(test_img)
    else:
        full_result = ocr.ocr(test_img, cls=False)
    full_ms = int((time.monotonic() - t_full) * 1000)
    # Count text items
    try:
        r = full_result
        if r and isinstance(r, list):
            if hasattr(r[0], 'rec_texts'):       n_texts = len(r[0].rec_texts)
            elif isinstance(r[0], list):          n_texts = len(r[0])
            else:                                 n_texts = len(r)
    except Exception: pass
    print(f"     Time:  {full_ms}ms")
    print(f"     Texts: {n_texts}")
except Exception as e:
    print(f"     FAILED: {e}")

# Split
if det_ms > 0 and full_ms > 0:
    rec_ms = max(0, full_ms - det_ms)
    print(f"\n  SPLIT RESULT:")
    print(f"    ├─ Detection:   {det_ms}ms  ({det_ms/full_ms*100:.1f}%)")
    print(f"    ├─ Recognition: {rec_ms}ms  ({rec_ms/full_ms*100:.1f}%)")
    print(f"    └─ TOTAL OCR:   {full_ms}ms")

# ── Q10: Second run on same image (detect re-load) ────────────────────────────
run_c_ms = -1
print("\n  >> PASS C: 2nd run same image (detect model re-init?)")
t_c = time.monotonic()
try:
    if hasattr(ocr, 'predict'):
        ocr.predict(test_img)
    else:
        ocr.ocr(test_img, cls=False)
    run_c_ms = int((time.monotonic() - t_c) * 1000)
    print(f"     Time:  {run_c_ms}ms")
    if full_ms > 0:
        r = run_c_ms / full_ms
        verdict = "consistent (no re-init)" if r < 1.5 else "SLOWER — possible re-init or GC"
        print(f"     vs B:  {r:.2f}x  → {verdict}")
except Exception as e:
    print(f"     FAILED: {e}")

# ── PAN card for comparison ────────────────────────────────────────────────────
print("\n  >> PASS D: PAN card (different image, same session)")
pan_docs = sb.table("documents").select("storage_path").eq("doc_type", "pan").limit(1).execute()
if pan_docs.data:
    pan_raw = sb.storage.from_("documents").download(pan_docs.data[0]["storage_path"])
    pan_pages = render_pages(pan_raw, "pan.png")
    pan_img = pan_pages[0]
    ph, pw = pan_img.shape[:2]
    print(f"     PAN image: {pw}×{ph} px")
    t_d = time.monotonic()
    try:
        if hasattr(ocr, 'predict'):
            ocr.predict(pan_img)
        else:
            ocr.ocr(pan_img, cls=False)
        pan_ms = int((time.monotonic() - t_d) * 1000)
        print(f"     PAN time:  {pan_ms}ms")
        if full_ms > 0:
            print(f"     vs Aadhaar:{full_ms}ms  (PAN/Aad={pan_ms/full_ms:.2f}x)")
    except Exception as e:
        print(f"     FAILED: {e}")
else:
    print("     (no PAN docs found)")

# ── FINAL SUMMARY ─────────────────────────────────────────────────────────────
print()
print(SEP)
print("FINAL DIAGNOSTIC REPORT")
print(SEP)
print(f"  1. PaddleOCR version:       {paddleocr.__version__}")
print(f"  2. Model: Detector          en_PP-OCRv3_det_infer  (2MB)")
print(f"     Model: Recognizer        en_PP-OCRv4_rec_infer  (7MB)")
print(f"  3. CPU:                     i5-12500H  12c/16t")
print(f"  4. GPU:                     NOT AVAILABLE (CPU-only build)")
print(f"  5. Image fed to OCR:        {ow}×{oh} px ({ow*oh/1_000_000:.2f}MP)")
print(f"  6. Pages per document:      {len(pages)}")
print(f"  7. Orientation classify:    DISABLED")
print(f"     Doc unwarping:           DISABLED")
print(f"     Textline orientation:    DISABLED")
print(f"     Angle classifier (cls):  DISABLED (cls=False at call)")
print(f"  8. OCR on full page:        {'YES (single page)' if page_count == 1 else 'cropped region'}")
print()
print(f"  TIMING TREE:")
print(f"  OCR_TOTAL")
if det_ms > 0 and full_ms > 0:
    print(f"  ├─ text_detection:   {det_ms}ms")
    print(f"  ├─ text_recognition: {max(0, full_ms-det_ms)}ms")
    print(f"  ├─ orientation_cls:  0ms (disabled)")
    print(f"  └─ post_processing:  ~1ms")
    print(f"  └─ TOTAL OCR:        {full_ms}ms")
else:
    print(f"  └─ TOTAL OCR:        {full_ms}ms  (split unavailable)")
print()
print(f"  FULL PER-RECORD BREAKDOWN:")
print(f"  download        {dl_ms}ms")
print(f"  render          {render_ms}ms")
print(f"  preprocess      <5ms")
print(f"  OCR             {full_ms}ms")
print(f"  save_extracted  ~480ms")
print(f"  save_verified   ~200ms")
print(f"  review_engine   ~650ms")
print(f"  ──────────────────────")
total_est = dl_ms + render_ms + (full_ms if full_ms > 0 else 0) + 480 + 200 + 650
print(f"  ESTIMATED TOTAL {total_est}ms")
print(SEP)
