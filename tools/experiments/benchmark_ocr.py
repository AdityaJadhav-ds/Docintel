import os, sys, time, logging
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.supabase_client import get_supabase
from app.services.validation_service import _download_document
from app.services.ocr_pipeline import process_document
import app.extraction.pipeline as pipeline
from paddleocr import PaddleOCR

def run_benchmark():
    sb = get_supabase()
    
    # 1. Get User 16's documents
    user_id = 16
    docs = sb.table("documents").select("*").eq("user_id", user_id).execute().data
    if not docs:
        print("No docs for user 16")
        return
        
    print(f"Found {len(docs)} documents for benchmark.")
    
    # Pre-download files
    files = {}
    for d in docs:
        b = _download_document(d["storage_path"])
        if b:
            files[d["id"]] = {"bytes": b, "type": d.get("doc_type", "unknown")}
            print(f"Downloaded doc {d['id']}, size: {len(b)} bytes")
    
    # Initialize models
    print("\n--- Initializing Model A (Default Server) ---")
    ocr_default = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        lang="en"
    )
    
    print("\n--- Initializing Model B (Mobile Det) ---")
    ocr_mobile = PaddleOCR(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
        lang="en",
        text_detection_model_name="PP-OCRv3_mobile_det",
        text_recognition_model_name="en_PP-OCRv5_mobile_rec"
    )

    # We will mock pipeline._get_ocr
    results = {}
    
    for model_name, ocr_instance in [("Model A (Default)", ocr_default), ("Model B (Mobile)", ocr_mobile)]:
        print(f"\n{'='*50}\nEvaluating {model_name}\n{'='*50}")
        pipeline._OCR = ocr_instance
        pipeline._OCR_LOCK.acquire() # prevent auto-init if it wasn't set, just in case, though it's set
        pipeline._OCR_LOCK.release()
        
        results[model_name] = {}
        
        for doc_id, doc_data in files.items():
            print(f"\nProcessing doc_id={doc_id} type={doc_data['type']} ...")
            t0 = time.time()
            res = process_document(doc_data["bytes"], doc_type_hint=doc_data["type"])
            t1 = time.time()
            
            elapsed = t1 - t0
            raw_text = res.get("raw_text", "")
            extracted = res.get("extracted", {})
            conf = res.get("ocr_confidence", 0.0)
            detected_type = res.get("doc_type", "unknown")
            
            results[model_name][doc_id] = {
                "elapsed": elapsed,
                "text_len": len(raw_text),
                "words": len(raw_text.split()),
                "extracted": extracted,
                "confidence": conf,
                "detected_type": detected_type
            }
            
            print(f"  Time:         {elapsed:.2f}s")
            print(f"  Detected:     {detected_type}")
            print(f"  Confidence:   {conf:.3f}")
            print(f"  Words found:  {len(raw_text.split())}")
            print(f"  Extracted:    {extracted}")

    # Print summary table
    print(f"\n{'='*70}\nCOMPARISON REPORT\n{'='*70}")
    
    for doc_id, doc_data in files.items():
        print(f"\nDocument ID: {doc_id} (Hint: {doc_data['type']})")
        print(f"{'Metric':<20} | {'Model A (Default)':<22} | {'Model B (Mobile)':<22}")
        print("-" * 70)
        
        ra = results["Model A (Default)"][doc_id]
        rb = results["Model B (Mobile)"][doc_id]
        
        print(f"{'Runtime':<20} | {ra['elapsed']:<21.2f}s | {rb['elapsed']:<21.2f}s")
        print(f"{'Confidence':<20} | {ra['confidence']:<22.3f} | {rb['confidence']:<22.3f}")
        print(f"{'Text Length (chars)':<20} | {ra['text_len']:<22} | {rb['text_len']:<22}")
        print(f"{'Word Count':<20} | {ra['words']:<22} | {rb['words']:<22}")
        print(f"{'Detected Type':<20} | {ra['detected_type']:<22} | {rb['detected_type']:<22}")
        
        ext_a = ra["extracted"]
        ext_b = rb["extracted"]
        
        print(f"\n  Extracted Fields:")
        all_keys = set(ext_a.keys()) | set(ext_b.keys())
        for k in sorted(all_keys):
            va = str(ext_a.get(k))
            vb = str(ext_b.get(k))
            match = "✅" if va == vb else "❌"
            print(f"  {k:<18} | {va:<22} | {vb:<22} {match}")

if __name__ == '__main__':
    # Disable logs so they don't clutter the benchmark
    logging.getLogger("docvalidator").setLevel(logging.ERROR)
    run_benchmark()
