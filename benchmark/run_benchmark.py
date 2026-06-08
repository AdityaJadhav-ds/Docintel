"""
benchmark/run_benchmark.py
──────────────────────────
Production stability benchmark for the DocValidator OCR pipeline.

Usage:
    python run_benchmark.py                     # run all PDFs, compare to baseline
    python run_benchmark.py --save-baseline     # run all PDFs, WRITE new baseline
    python run_benchmark.py --pdf path/to.pdf   # run single PDF only

Measures per PDF:
    - page_count        (must match baseline exactly)
    - word_count        (must be within ±15% of baseline)
    - line_count        (must be within ±20% of baseline)
    - processing_ms     (informational — not a pass/fail gate)
    - success           (must be True)

Exit codes:
    0 — all tests passed
    1 — one or more tests failed
"""
import argparse
import json
import pathlib
import sys
import time
import requests

# ── Config ───────────────────────────────────────────────────────────────────
API_BASE       = "http://127.0.0.1:8000"
PDFS_DIR       = pathlib.Path(__file__).parent / "pdfs"
BASELINE_FILE  = pathlib.Path(__file__).parent / "baseline.json"
RESULTS_DIR    = pathlib.Path(__file__).parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

POLL_INTERVAL  = 1.0    # seconds between status polls
POLL_TIMEOUT   = 600    # seconds max wait per PDF (10 min)

WORD_TOLERANCE  = 0.15  # ±15%
LINE_TOLERANCE  = 0.20  # ±20%

# ── Colours for terminal ──────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def ok(msg):  print(f"  {GREEN}✓{RESET} {msg}")
def fail(msg):print(f"  {RED}✗{RESET} {msg}")
def info(msg):print(f"  {CYAN}·{RESET} {msg}")
def warn(msg):print(f"  {YELLOW}!{RESET} {msg}")


# ── API helpers ───────────────────────────────────────────────────────────────
def check_backend():
    try:
        r = requests.get(f"{API_BASE}/api/health", timeout=5)
        return r.ok
    except Exception:
        return False


def run_ocr(pdf_path: pathlib.Path) -> dict:
    """Submit PDF, poll until done, return result dict."""
    with open(pdf_path, "rb") as f:
        r = requests.post(
            f"{API_BASE}/api/ocr/pipeline/start",
            files={"file": (pdf_path.name, f, "application/pdf")},
            timeout=30,
        )
    r.raise_for_status()
    run_id = r.json()["run_id"]

    # Check if result came back immediately (cache hit)
    start_data = r.json()
    if start_data.get("status") == "done" or start_data.get("cached"):
        # Already complete — fetch result directly
        res = requests.get(f"{API_BASE}/api/ocr/pipeline/result/{run_id}", timeout=30).json()
        return res.get("result") or res

    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        st = requests.get(f"{API_BASE}/api/ocr/pipeline/status/{run_id}", timeout=10).json()
        # Status endpoint returns overall_status: "done" | "running" | "failed"
        overall = st.get("overall_status", "")
        if overall in ("done", "failed"):
            break
    else:
        raise TimeoutError(f"Timed out after {POLL_TIMEOUT}s waiting for {pdf_path.name}")

    res = requests.get(f"{API_BASE}/api/ocr/pipeline/result/{run_id}", timeout=30).json()
    return res.get("result") or res


# ── Metrics extraction ────────────────────────────────────────────────────────
def extract_metrics(result: dict, elapsed_s: float) -> dict:
    meta  = result.get("metadata", {})
    lines = result.get("lines", [])
    return {
        "success":        result.get("success", False),
        "page_count":     meta.get("page_count", 0),
        "word_count":     result.get("word_count", 0),
        "line_count":     meta.get("line_count", len(lines)),
        "processing_ms":  result.get("processing_time_ms", result.get("elapsed_ms", 0)),
        "elapsed_s":      round(elapsed_s, 2),
        "overall_status": result.get("overall_status", "?"),
    }


# ── Comparison ────────────────────────────────────────────────────────────────
def compare(name: str, measured: dict, baseline: dict) -> list[str]:
    """Returns list of failure strings. Empty list = all passed."""
    failures = []

    if not measured["success"]:
        failures.append(f"success=False (status={measured['overall_status']})")

    if measured["page_count"] != baseline["page_count"]:
        failures.append(
            f"page_count mismatch: got {measured['page_count']}, expected {baseline['page_count']}"
        )

    def within(key, tol):
        got = measured[key]; exp = baseline[key]
        if exp == 0:
            return got == 0
        return abs(got - exp) / exp <= tol

    if not within("word_count", WORD_TOLERANCE):
        failures.append(
            f"word_count out of range: got {measured['word_count']}, "
            f"expected {baseline['word_count']} ±{int(WORD_TOLERANCE*100)}%"
        )

    if not within("line_count", LINE_TOLERANCE):
        failures.append(
            f"line_count out of range: got {measured['line_count']}, "
            f"expected {baseline['line_count']} ±{int(LINE_TOLERANCE*100)}%"
        )

    return failures


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="DocValidator OCR Benchmark")
    parser.add_argument("--save-baseline", action="store_true",
                        help="Write current results as new golden baseline")
    parser.add_argument("--pdf", type=str, default=None,
                        help="Run a single PDF instead of the full suite")
    args = parser.parse_args()

    # ── Check backend is alive ────────────────────────────────────────────────
    print(f"\n{BOLD}DocValidator OCR Benchmark{RESET}")
    print(f"{'─'*50}")
    if not check_backend():
        print(f"{RED}ERROR: Backend not reachable at {API_BASE}{RESET}")
        print("Start it with:  uvicorn main:app --reload  (from backend_v2/)")
        sys.exit(1)
    ok(f"Backend alive at {API_BASE}")

    # ── Collect PDFs ──────────────────────────────────────────────────────────
    if args.pdf:
        pdfs = [pathlib.Path(args.pdf)]
    else:
        PDFS_DIR.mkdir(exist_ok=True)
        pdfs = sorted(PDFS_DIR.glob("*.pdf"))
        if not pdfs:
            warn(f"No PDFs found in {PDFS_DIR}")
            warn("Add PDFs to benchmark/pdfs/ then run again.")
            sys.exit(0)

    # ── Load baseline ─────────────────────────────────────────────────────────
    baseline = {}
    if BASELINE_FILE.exists() and not args.save_baseline:
        baseline = json.loads(BASELINE_FILE.read_text())
        info(f"Loaded baseline from {BASELINE_FILE.name} ({len(baseline)} entries)")
    elif args.save_baseline:
        warn("--save-baseline mode: writing new golden baseline after run")
    else:
        warn("No baseline.json found — first run will only record metrics")

    # ── Run each PDF ──────────────────────────────────────────────────────────
    all_results  = {}
    total_pass   = 0
    total_fail   = 0
    total_skip   = 0

    for pdf in pdfs:
        print(f"\n{BOLD}[{pdf.name}]{RESET}")
        t0 = time.time()
        try:
            result  = run_ocr(pdf)
            elapsed = time.time() - t0
            metrics = extract_metrics(result, elapsed)
        except Exception as e:
            fail(f"Pipeline error: {e}")
            total_fail += 1
            all_results[pdf.name] = {"error": str(e)}
            continue

        # Print measured metrics
        info(f"pages={metrics['page_count']}  words={metrics['word_count']}  "
             f"lines={metrics['line_count']}  time={metrics['elapsed_s']}s  "
             f"(api={metrics['processing_ms']}ms)")

        all_results[pdf.name] = metrics

        # Compare or record
        if pdf.name in baseline:
            failures = compare(pdf.name, metrics, baseline[pdf.name])
            if failures:
                for f_msg in failures:
                    fail(f_msg)
                total_fail += 1
            else:
                ok("All checks passed ✓")
                total_pass += 1
        else:
            warn("No baseline entry — skipping comparison (run --save-baseline to record)")
            total_skip += 1

    # ── Save baseline if requested ────────────────────────────────────────────
    if args.save_baseline:
        # Merge new results into existing baseline
        merged = {**baseline, **all_results}
        BASELINE_FILE.write_text(json.dumps(merged, indent=2))
        ok(f"Baseline saved → {BASELINE_FILE}")

    # ── Save timestamped results ──────────────────────────────────────────────
    ts      = time.strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"run_{ts}.json"
    out_path.write_text(json.dumps(all_results, indent=2))
    info(f"Results saved → {out_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"{BOLD}Summary:{RESET}  "
          f"{GREEN}{total_pass} passed{RESET}  "
          f"{RED}{total_fail} failed{RESET}  "
          f"{YELLOW}{total_skip} no-baseline{RESET}")
    print()

    sys.exit(1 if total_fail > 0 else 0)


if __name__ == "__main__":
    main()
