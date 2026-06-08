"""
warm_user_profile.py
=====================
Runs process_user_documents() on ONE already-processed user and captures
the per-stage TIMING log lines that the validation service already emits.

Reports a clean breakdown:
  download_aadhaar
  ocr_aadhaar
  download_pan
  ocr_pan
  save_extracted (per doc)
  save_verified  (per doc)
  review_engine  (per doc)
  TOTAL_DOC      (per doc)
  TOTAL_USER

This uses the WARMED engine (rec_batch=1) — no cold-start penalty.

Usage:
    cd backend
    venv\\Scripts\\python.exe warm_user_profile.py
"""
import sys, os, re, io, time, logging
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ["FLAGS_enable_pir_api"]         = "0"
os.environ["FLAGS_enable_pir_in_executor"] = "0"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Intercept [TIMING] log lines ──────────────────────────────────────────────
captured_timing = []

class TimingCapture(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        if "[TIMING]" in msg:
            captured_timing.append(msg)

root = logging.getLogger("docvalidator")
root.setLevel(logging.INFO)
handler = TimingCapture()
handler.setFormatter(logging.Formatter("%(message)s"))
root.addHandler(handler)
# Silence all other loggers
logging.getLogger("paddleocr").setLevel(logging.ERROR)
logging.getLogger("paddle").setLevel(logging.ERROR)

# ── Run on a known warm user (user 9) ────────────────────────────────────────
TARGET_USER = 9

print(f"\nWarm-user profile: user_id={TARGET_USER}")
print("OCR config: PP-OCRv3_mobile_det + rec_batch=1  (new config)")
print()

from app.services.validation_service import process_user_documents

t0 = time.monotonic()
result = process_user_documents(TARGET_USER)
wall_s = time.monotonic() - t0

# ── Parse captured TIMING lines ───────────────────────────────────────────────
# Format: [TIMING] user=9 doc=17 type=aadhaar  stage=download  850ms  size=47KB
timings = {}
for line in captured_timing:
    # Extract stage and ms
    m_stage = re.search(r"stage=(\S+)", line)
    m_ms    = re.search(r"(\d+)ms", line)
    m_doc   = re.search(r"doc=(\d+)", line)
    m_type  = re.search(r"type=(\w+)", line)
    m_conf  = re.search(r"conf=([\d.]+)", line)
    m_status= re.search(r"status=(\w+)", line)
    m_size  = re.search(r"size=(\S+)", line)
    m_dec   = re.search(r"decision=(\w+)", line)

    if not (m_stage and m_ms):
        continue

    stage  = m_stage.group(1)
    ms     = int(m_ms.group(1))
    doc    = m_doc.group(1) if m_doc else "-"
    dtype  = m_type.group(1) if m_type else "-"
    conf   = m_conf.group(1) if m_conf else ""
    status = m_status.group(1) if m_status else ""
    size   = m_size.group(1) if m_size else ""
    dec    = m_dec.group(1) if m_dec else ""

    key = f"{dtype}/{stage}"
    timings[key] = {"ms": ms, "doc": doc, "conf": conf,
                    "status": status, "size": size, "decision": dec}

# ── Print breakdown ───────────────────────────────────────────────────────────
print(f"  {'Stage':<35} {'Time':>8}  Notes")
print(f"  {'-'*65}")

STAGE_ORDER = [
    ("aadhaar/download",       "Download Aadhaar"),
    ("aadhaar/ocr_pipeline",   "OCR  Aadhaar"),
    ("aadhaar/validation",     "Validate Aadhaar"),
    ("aadhaar/save_extracted", "Save extracted  Aadhaar"),
    ("aadhaar/save_verified",  "Save verified   Aadhaar"),
    ("aadhaar/review_engine",  "Review engine   Aadhaar"),
    ("aadhaar/TOTAL_DOC",      "TOTAL  Aadhaar"),
    ("pan/download",           "Download PAN"),
    ("pan/ocr_pipeline",       "OCR  PAN"),
    ("pan/validation",         "Validate PAN"),
    ("pan/save_extracted",     "Save extracted  PAN"),
    ("pan/save_verified",      "Save verified   PAN"),
    ("pan/review_engine",      "Review engine   PAN"),
    ("pan/TOTAL_DOC",          "TOTAL  PAN"),
]

total_download = 0
total_ocr      = 0
total_save     = 0
total_review   = 0

for key, label in STAGE_ORDER:
    t = timings.get(key)
    if not t:
        continue
    ms = t["ms"]

    extra = ""
    if "download"  in key: extra = f"size={t['size']}";           total_download += ms
    if "ocr"       in key: extra = f"conf={t['conf']}";           total_ocr      += ms
    if "save"      in key:                                         total_save     += ms
    if "review"    in key: extra = f"decision={t['decision']}";   total_review   += ms

    bar = "#" * max(1, ms // 1000)
    sep = "----" if "TOTAL" in key else "    "
    print(f"  {sep}{label:<31} {ms:>6}ms  {bar}  {extra}")

print(f"  {'-'*65}")
print(f"\n  SUBTOTALS:")
print(f"    Download (both docs):  {total_download:>6}ms  ({total_download/1000:.1f}s)")
print(f"    OCR (both docs):       {total_ocr:>6}ms  ({total_ocr/1000:.1f}s)")
print(f"    Save ops:              {total_save:>6}ms  ({total_save/1000:.1f}s)")
print(f"    Review engine:         {total_review:>6}ms  ({total_review/1000:.1f}s)")
accounted = total_download + total_ocr + total_save + total_review
other     = int(wall_s * 1000) - accounted
print(f"    Other (dup-detect etc):{other:>6}ms  ({other/1000:.1f}s)")
print(f"    WALL CLOCK:            {int(wall_s*1000):>6}ms  ({wall_s:.1f}s)")

print(f"\n  OCR share of wall time: {total_ocr/wall_s/10:.0f}%")
print(f"  Download share:         {total_download/wall_s/10:.0f}%")
print()

# ── Raw timing lines (for reference) ─────────────────────────────────────────
print("\n  Raw TIMING log lines:")
for line in captured_timing:
    if "[TIMING]" in line:
        print(f"    {line.strip()}")
