# DocValidator OCR Benchmark Suite

## Purpose

Validate **consistency and reliability** of the OCR pipeline across diverse document types.  
One passing run is not enough — this suite proves *repeatability*.

---

## Directory Structure

```
benchmark/
├── run_benchmark.py      ← the runner
├── baseline.json         ← golden expected values (auto-generated)
├── pdfs/                 ← put your test PDFs here
│   ├── 1page_scanned.pdf
│   ├── 4page_bank_statement.pdf
│   ├── 12page_statement.pdf
│   ├── low_quality_scan.pdf
│   └── digital_vector.pdf
└── results/              ← timestamped run logs (auto-generated)
    ├── run_20260528_120000.json
    └── run_20260528_130000.json
```

---

## Setup

1. **Install requests** (if not already):
   ```bash
   cd backend_v2
   venv\Scripts\pip install requests
   ```

2. **Start the backend**:
   ```bash
   cd backend_v2
   venv\Scripts\python -m uvicorn main:app --reload
   ```

3. **Put your test PDFs** into `benchmark/pdfs/`

---

## Workflow

### Step 1 — Record the golden baseline (first time only)
```bash
cd benchmark
..\backend_v2\venv\Scripts\python run_benchmark.py --save-baseline
```
This runs all PDFs and writes `baseline.json` with the expected metrics.

### Step 2 — Run the suite (every test after that)
```bash
..\backend_v2\venv\Scripts\python run_benchmark.py
```
Compares current output against the golden baseline.

### Step 3 — Test a single PDF quickly
```bash
..\backend_v2\venv\Scripts\python run_benchmark.py --pdf pdfs/4page_bank_statement.pdf
```

---

## Pass/Fail Criteria

| Metric | Tolerance | Rationale |
|---|---|---|
| `page_count` | Exact match | Pages must never be lost |
| `word_count` | ±15% | Scanned docs have minor OCR variation |
| `line_count` | ±20% | Line merging heuristics can vary slightly |
| `success` | Must be `True` | Pipeline must not crash |
| `processing_ms` | Informational only | Not a gate — speeds can vary |

---

## Recommended Test PDF Set

| File | Pages | Type | Tests |
|---|---|---|---|
| `1page_scanned.pdf` | 1 | Scanned | Baseline accuracy |
| `4page_bank_statement.pdf` | 4 | Dense scanned | Multi-page, polling |
| `12page_statement.pdf` | 12 | Dense scanned | Memory stability |
| `low_quality_scan.pdf` | any | Degraded scan | Noise filter |
| `digital_vector.pdf` | any | Digital PDF | Vector text path |

---

## Interpreting Results

```
✓  All checks passed            ← healthy
✗  word_count out of range      ← OCR regression (check normalizer)
✗  page_count mismatch          ← renderer dropped a page (check pdf_renderer)
✗  success=False                ← pipeline crash (check backend logs)
!  No baseline entry            ← new file, run --save-baseline
```

---

## After Every Pipeline Change

Run the benchmark before and after the change:
```
Before: run_20260528_120000.json   (save as "before")
Change: apply optimization / fix
After:  run_20260528_130000.json   (compare)
```

If `after` results are within tolerance of `baseline.json` → **safe to ship**.  
If any metric regresses → **revert and debug**.
