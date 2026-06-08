"""
perf_single.py — Single-user OCR timing probe
===============================================
Runs process_user_documents() on ONE user and prints a clean
[PERF] summary table.  Zero changes to existing code.

Usage:
    cd backend
    venv\\Scripts\\python.exe perf_single.py [user_id]
"""
import os, sys, time, io, logging

# Suppress paddle/paddleocr noise so [PERF] lines are easy to spot
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Capture [TIMING] lines emitted by validation_service
timing_lines = []
_original_info = None

import app.core.logger  # noqa: ensure logger exists before patching

from app.core.logger import logger as _logger

class _TimingCapture(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        if "[TIMING]" in msg or "[PERF]" in msg:
            timing_lines.append(msg)

_capture = _TimingCapture()
_capture.setLevel(logging.DEBUG)
logging.getLogger("docvalidator").addHandler(_capture)

# ── Now import the real pipeline (no stubs needed — same process as backend) ──
from app.services.validation_service import process_user_documents

TARGET_USER = int(sys.argv[1]) if len(sys.argv) > 1 else 16

print(f"\n{'='*60}")
print(f"PERF PROBE — user_id={TARGET_USER}")
print(f"{'='*60}\n")

wall_start = time.perf_counter()
result     = process_user_documents(TARGET_USER)
wall_total = time.perf_counter() - wall_start

print(f"\n{'='*60}")
print("RAW [TIMING] LOG LINES:")
print(f"{'='*60}")
for line in timing_lines:
    # Strip the timestamp prefix for readability
    core = line.split("] ", 2)[-1] if "] " in line else line
    print(core)

print(f"\n{'='*60}")
print("CLEAN SUMMARY TABLE:")
print(f"{'='*60}")

import re
stages = {}
for line in timing_lines:
    m = re.search(r"stage=(\S+)\s+(\d+)ms", line)
    if m:
        stage, ms = m.group(1), int(m.group(2))
        stages.setdefault(stage, []).append(ms)

for stage, values in stages.items():
    avg = sum(values) / len(values)
    if len(values) == 1:
        print(f"  {stage:<25} {values[0]:>7}ms")
    else:
        print(f"  {stage:<25} {int(avg):>7}ms  (×{len(values)} docs: {values})")

print(f"\n  {'WALL CLOCK TOTAL':<25} {wall_total*1000:>7.0f}ms  ({wall_total:.2f}s)\n")
print(f"  overall_status = {result.get('overall_status', result.get('error', '?'))}")
print(f"  docs processed = {result.get('total_docs', 0)}")
print(f"{'='*60}\n")
