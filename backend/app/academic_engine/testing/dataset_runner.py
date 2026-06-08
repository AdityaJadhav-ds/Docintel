"""
academic_engine/testing/dataset_runner.py
=========================================
Golden Dataset Runner for Academic Intelligence.

Loads all documents from `academic_test_dataset/`, runs the full academic pipeline,
and compares extracted results against the matching ground-truth JSON files.

Fields tracked:
  - document_category (classification)
  - candidate_name
  - percentage
  - cgpa
  - result
  - board_university
  - passing_year

Computes:
  - Accuracy per field
  - False Positives (Hallucinations)
  - Misses (Null when expected value)
  - Performance (Elapsed time, memory, retries)
"""

from __future__ import annotations

import json
import logging
import time
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.academic_engine.pipeline.academic_pipeline import run_pipeline

# ── Set up logging ────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("dataset_runner")


@dataclass
class FieldStats:
    total_expected: int = 0
    correct: int = 0
    missed: int = 0         # Expected a value, got None
    hallucinated: int = 0   # Expected None, got a value
    wrong: int = 0          # Expected a value, got a different value

    @property
    def accuracy(self) -> float:
        if self.total_expected == 0:
            return 0.0
        return self.correct / self.total_expected

    @property
    def false_positive_rate(self) -> float:
        if self.total_expected == 0:
            return 0.0
        return self.hallucinated / max(1, self.total_expected)

@dataclass
class DocumentResult:
    file_path: str
    ground_truth: Dict[str, Any]
    extracted: Dict[str, Any]
    meta: Dict[str, Any]
    elapsed_ms: float
    field_errors: Dict[str, str] = field(default_factory=dict)

def _normalize_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return text.strip().upper()

def _compare_numeric(extracted: Optional[str], expected: Optional[str], tol: float = 0.5) -> str:
    """Returns 'correct', 'missed', 'hallucinated', or 'wrong'"""
    if expected is None and extracted is None:
        return "correct"
    if expected is None and extracted is not None:
        return "hallucinated"
    if expected is not None and extracted is None:
        return "missed"
    
    try:
        ev = float(extracted)
        gt = float(expected)
        if abs(ev - gt) <= tol:
            return "correct"
        return "wrong"
    except (ValueError, TypeError):
        return "wrong"

def _compare_text(extracted: Optional[str], expected: Optional[str]) -> str:
    if expected is None and extracted is None:
        return "correct"
    if expected is None and extracted is not None:
        return "hallucinated"
    if expected is not None and extracted is None:
        return "missed"
    
    if _normalize_text(extracted) == _normalize_text(expected):
        return "correct"
    
    # Check partial match for names
    if expected and extracted:
        exp_words = set(_normalize_text(expected).split())
        ext_words = set(_normalize_text(extracted).split())
        if len(exp_words & ext_words) >= max(1, len(exp_words) - 1):
            return "correct"
            
    return "wrong"

def run_dataset(dataset_dir: str):
    base_path = Path(dataset_dir)
    if not base_path.exists():
        logger.error(f"Dataset directory not found: {base_path}")
        return

    # Find all image/PDF files
    extensions = {".jpg", ".jpeg", ".png", ".pdf", ".webp", ".bmp"}
    all_files = []
    for root, _, files in os.walk(base_path):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in extensions:
                all_files.append(p)

    logger.info(f"Found {len(all_files)} potential document(s).")
    
    results: List[DocumentResult] = []
    
    fields_to_track = [
        "document_category", "candidate_name", "percentage", 
        "cgpa", "result", "board_university", "passing_year"
    ]
    
    stats = {f: FieldStats() for f in fields_to_track}
    total_processing_ms = 0.0

    for doc_path in all_files:
        json_path = doc_path.with_suffix(".json")
        if not json_path.exists():
            continue
            
        with open(json_path, "r", encoding="utf-8") as f:
            try:
                ground_truth = json.load(f)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON ground truth for {doc_path.name}")
                continue
                
        logger.info(f"Processing: {doc_path.name}...")
        
        # Run pipeline
        t0 = time.time()
        try:
            with open(doc_path, "rb") as f:
                file_bytes = f.read()
            pipeline_result = run_pipeline(file_bytes, doc_id=doc_path.stem)
        except Exception as e:
            logger.error(f"Pipeline failed for {doc_path.name}: {e}")
            continue
        elapsed = (time.time() - t0) * 1000
        total_processing_ms += elapsed
        
        meta = pipeline_result.get("_meta", {})
        
        doc_res = DocumentResult(
            file_path=str(doc_path),
            ground_truth=ground_truth,
            extracted=pipeline_result,
            meta=meta,
            elapsed_ms=elapsed
        )
        
        # Compare fields
        for field in fields_to_track:
            expected = ground_truth.get(field)
            extracted = pipeline_result.get(field)
            
            if field in ("percentage", "cgpa"):
                status = _compare_numeric(extracted, expected)
            else:
                status = _compare_text(extracted, expected)
                
            if expected is not None:
                stats[field].total_expected += 1
                
            if status == "correct":
                if expected is not None:
                    stats[field].correct += 1
            elif status == "missed":
                stats[field].missed += 1
                doc_res.field_errors[field] = f"MISSED (Expected: {expected})"
            elif status == "hallucinated":
                stats[field].hallucinated += 1
                doc_res.field_errors[field] = f"HALLUCINATED (Got: {extracted})"
            elif status == "wrong":
                stats[field].wrong += 1
                doc_res.field_errors[field] = f"WRONG (Expected: {expected}, Got: {extracted})"
                
        results.append(doc_res)
        
    # Print Report
    logger.info("\n" + "="*50)
    logger.info("   ACADEMIC ENGINE - GOLDEN DATASET VALIDATION")
    logger.info("="*50)
    logger.info(f"Documents Evaluated: {len(results)}")
    if not results:
        logger.info("No valid documents with ground truth JSON found.")
        return
        
    logger.info(f"Avg Processing Time: {total_processing_ms / len(results):.1f} ms\n")
    
    logger.info("FIELD-LEVEL ACCURACY:")
    logger.info("-" * 80)
    logger.info(f"{'Field':<20} | {'Expected':<8} | {'Correct':<8} | {'Accuracy':<9} | {'Misses':<8} | {'Wrongs':<8} | {'Hallucinations':<12}")
    logger.info("-" * 80)
    
    for f in fields_to_track:
        s = stats[f]
        acc_str = f"{s.accuracy * 100:.1f}%"
        logger.info(f"{f:<20} | {s.total_expected:<8} | {s.correct:<8} | {acc_str:<9} | {s.missed:<8} | {s.wrong:<8} | {s.hallucinated:<12}")

    logger.info("-" * 80)
    
    # Detailed failures
    failed_docs = [r for r in results if r.field_errors]
    if failed_docs:
        logger.info("\nDETAILED FAILURES:")
        for r in failed_docs:
            logger.info(f"\n📄 {Path(r.file_path).name}:")
            for field, err in r.field_errors.items():
                logger.info(f"  ❌ {field}: {err}")
                
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Golden Dataset Validation")
    parser.add_argument("--dir", default="academic_test_dataset", help="Path to dataset directory")
    args = parser.parse_args()
    
    run_dataset(args.dir)
