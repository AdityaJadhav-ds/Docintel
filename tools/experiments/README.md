# Experiments & Benchmarking Scripts

These scripts were used during OCR optimization and system diagnostics.
They are **not part of the production application** but are preserved here
for reference and future performance testing.

| Script | Purpose |
|---|---|
| `benchmark_ocr.py` | OCR throughput benchmarking |
| `bench_det_limit.py` | PaddleOCR detection limit testing |
| `inspect_fetch_user.py` | Supabase user fetch diagnostics |
| `ocr_deep_profile.py` | Deep profiling of OCR pipeline stages |
| `profile_duplicate_detector.py` | Profiling duplicate detector performance |
| `warm_user_profile.py` | Pre-warming user profile cache |
| `batch_50_monitor.py` | Batch-50 job monitoring |
| `check_state.py` | System state inspector |
| `verify_routing.py` | API routing verification |
| `test_ocr_thread_safety.py` | Thread-safety stress test for OCR engine |

## Usage

Run from the `backend/` directory with the venv activated:

```bash
cd backend
venv\Scripts\activate
python ..\tools\experiments\benchmark_ocr.py
```
