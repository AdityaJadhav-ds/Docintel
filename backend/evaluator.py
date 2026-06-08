"""
evaluator.py
=============
Accuracy evaluator for the academic extraction pipeline.

Compares pipeline output against ground_truth.json.

Usage:
  cd backend
  .\\venv\\Scripts\\python.exe evaluator.py

Output:
  - Per-document result table
  - Aggregate accuracy metrics
  - Saved to logs/evaluation_report.json
"""
import os
import sys
import json
import glob
import time
import cv2

sys.path.insert(0, os.path.dirname(__file__))

from app.academic_engine.master_pipeline import MasterPipeline

GROUND_TRUTH_PATH = os.path.join(os.path.dirname(__file__), "test_documents", "ground_truth.json")
TEST_DOCS_DIR     = os.path.join(os.path.dirname(__file__), "test_documents")
REPORT_PATH       = os.path.join(os.path.dirname(__file__), "logs", "evaluation_report.json")

os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)


# ─────────────────────────────────────────────────────────────────────
# METRIC HELPERS
# ─────────────────────────────────────────────────────────────────────

def _pct_match(predicted, expected, tolerance=2.0) -> bool:
    """Percentage is correct if within ±tolerance percent points."""
    if predicted is None or expected is None:
        return predicted == expected
    try:
        return abs(float(predicted) - float(expected)) <= tolerance
    except (ValueError, TypeError):
        return False


def _name_match(predicted, expected) -> bool:
    if predicted is None or expected is None:
        return predicted == expected
    p = str(predicted).lower().strip()
    e = str(expected).lower().strip()
    # Accept if all words in expected appear in predicted (order-insensitive)
    e_parts = e.split()
    return all(part in p for part in e_parts)


def _marks_match(predicted, expected, tolerance=1.0) -> bool:
    if predicted is None or expected is None:
        return predicted == expected
    try:
        return abs(float(predicted) - float(expected)) <= tolerance
    except (ValueError, TypeError):
        return False


def _result_match(predicted, expected) -> bool:
    if predicted is None or expected is None:
        return predicted == expected
    return str(predicted).upper().strip() == str(expected).upper().strip()


# ─────────────────────────────────────────────────────────────────────
# EVALUATOR
# ─────────────────────────────────────────────────────────────────────

def evaluate():
    if not os.path.exists(GROUND_TRUTH_PATH):
        print("[Evaluator] No ground_truth.json found. Add documents to test_documents/.")
        return

    with open(GROUND_TRUTH_PATH, "r", encoding="utf-8") as f:
        gt_data = json.load(f)

    documents = gt_data.get("documents", [])
    if not documents:
        print("[Evaluator] ground_truth.json has no documents yet.")
        print("  → Add test images to backend/test_documents/")
        print("  → Add entries to ground_truth.json matching each file")
        return

    pipeline = MasterPipeline()

    results = []
    field_hits   = {"name": 0, "percentage": 0, "obtained_marks": 0, "total_marks": 0, "result": 0}
    field_trials = {"name": 0, "percentage": 0, "obtained_marks": 0, "total_marks": 0, "result": 0}

    print(f"\n{'='*70}")
    print(f"  ACADEMIC EXTRACTION EVALUATOR — {len(documents)} documents")
    print(f"{'='*70}\n")

    for entry in documents:
        filename = entry.get("filename", "")
        expected = entry.get("expected", {})
        img_path = os.path.join(TEST_DOCS_DIR, filename)

        if not os.path.exists(img_path):
            print(f"  [SKIP] {filename} — file not found")
            continue

        image = cv2.imread(img_path)
        if image is None:
            print(f"  [SKIP] {filename} — could not load image")
            continue

        t0 = time.time()
        try:
            output = pipeline.process_document(image, upload_id=os.path.splitext(filename)[0])
            fields = output.get("valid_fields", {})
            status = output.get("status", "error")
        except Exception as e:
            fields = {}
            status = f"crash: {e}"
        elapsed = round(time.time() - t0, 2)

        def _get_val(field_name):
            f = fields.get(field_name, {})
            if isinstance(f, dict):
                return f.get("value")
            return f

        doc_result = {
            "filename": filename,
            "doc_type": entry.get("doc_type"),
            "variant": entry.get("variant"),
            "status": status,
            "elapsed_s": elapsed,
            "fields": {},
        }

        # ── Name ──
        exp_name = expected.get("name")
        pred_name = _get_val("name")
        if exp_name is not None:
            hit = _name_match(pred_name, exp_name)
            field_hits["name"] += int(hit)
            field_trials["name"] += 1
            doc_result["fields"]["name"] = {"expected": exp_name, "predicted": pred_name, "match": hit}

        # ── Percentage ──
        exp_pct = expected.get("percentage")
        pred_pct = _get_val("percentage")
        if exp_pct is not None:
            hit = _pct_match(pred_pct, exp_pct)
            field_hits["percentage"] += int(hit)
            field_trials["percentage"] += 1
            doc_result["fields"]["percentage"] = {"expected": exp_pct, "predicted": pred_pct, "match": hit}

        # ── Obtained Marks ──
        exp_obt = expected.get("obtained_marks")
        pred_obt = _get_val("obtained_marks")
        if exp_obt is not None:
            hit = _marks_match(pred_obt, exp_obt)
            field_hits["obtained_marks"] += int(hit)
            field_trials["obtained_marks"] += 1
            doc_result["fields"]["obtained_marks"] = {"expected": exp_obt, "predicted": pred_obt, "match": hit}

        # ── Total Marks ──
        exp_tot = expected.get("total_marks")
        pred_tot = _get_val("total_marks")
        if exp_tot is not None:
            hit = _marks_match(pred_tot, exp_tot)
            field_hits["total_marks"] += int(hit)
            field_trials["total_marks"] += 1
            doc_result["fields"]["total_marks"] = {"expected": exp_tot, "predicted": pred_tot, "match": hit}

        # ── Result ──
        exp_res = expected.get("result")
        pred_res = _get_val("result")
        if exp_res is not None:
            hit = _result_match(pred_res, exp_res)
            field_hits["result"] += int(hit)
            field_trials["result"] += 1
            doc_result["fields"]["result"] = {"expected": exp_res, "predicted": pred_res, "match": hit}

        results.append(doc_result)

        # ── Print row ──
        matches = [v["match"] for v in doc_result["fields"].values()]
        overall_doc = f"{sum(matches)}/{len(matches)}" if matches else "N/A"
        print(f"  [{filename}]  {overall_doc} fields matched  ({elapsed}s)  [{entry.get('doc_type','?')} / {entry.get('variant','?')}]")
        for fname, fdata in doc_result["fields"].items():
            mark = "✓" if fdata["match"] else "✗"
            print(f"      {mark} {fname}: expected={fdata['expected']}  predicted={fdata['predicted']}")

    # ── Aggregate metrics ──
    print(f"\n{'='*70}")
    print("  AGGREGATE ACCURACY")
    print(f"{'='*70}")

    total_hits = 0
    total_trials = 0
    field_acc = {}
    for field in field_hits:
        trials = field_trials[field]
        hits   = field_hits[field]
        acc    = round(hits / trials * 100, 1) if trials > 0 else None
        field_acc[field] = acc
        total_hits   += hits
        total_trials += trials
        bar = "█" * int((acc or 0) / 5) if acc is not None else "—"
        print(f"  {field:<20} {acc if acc is not None else 'N/A':>5}%  [{bar}]  ({hits}/{trials})")

    overall_acc = round(total_hits / total_trials * 100, 1) if total_trials > 0 else None
    print(f"\n  {'OVERALL':<20} {overall_acc if overall_acc is not None else 'N/A':>5}%  ({total_hits}/{total_trials})\n")

    if overall_acc is not None:
        target = 95.0
        if overall_acc >= target:
            print(f"  ✅ TARGET MET: {overall_acc}% ≥ {target}%")
        else:
            print(f"  ❌ TARGET NOT MET: {overall_acc}% < {target}% — stabilization continues.")

    # ── Save report ──
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_documents": len(results),
        "overall_accuracy_pct": overall_acc,
        "target_accuracy_pct": 95.0,
        "target_met": (overall_acc or 0) >= 95.0,
        "field_accuracy": field_acc,
        "documents": results,
    }
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Report saved → {REPORT_PATH}\n")
    return report


if __name__ == "__main__":
    evaluate()
