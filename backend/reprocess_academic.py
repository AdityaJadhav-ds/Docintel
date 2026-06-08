"""
reprocess_academic.py
======================
Re-runs academic OCR on all existing extracted_data rows where
aadhaar_number (grade) AND pan_number (percentage) are both NULL,
i.e., the OCR produced no result.

Uses the same direct pytesseract fallback added to routes.py,
so SPI/CGPA/CPI is now correctly extracted from degree/diploma PDFs.

Usage: python reprocess_academic.py
       python reprocess_academic.py --user_id 168
       python reprocess_academic.py --doc_type degree
"""

import os
import io
import re
import sys
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

os.chdir(os.path.dirname(__file__) or ".")
sys.path.insert(0, os.path.abspath("."))

from dotenv import load_dotenv
load_dotenv()


def extract_grade_from_text(text: str):
    """Extract SPI/CGPA/CPI from raw OCR text. Returns (grade_str, type_label) or (None, None)."""
    cpi_m  = re.search(r'\bCPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE)
    cgpa_m = re.search(r'\bCGPA\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE)
    spi_m  = re.search(r'\bSPI\s*[:\s]\s*([0-9]\.[0-9]{2,3})\b', text, re.IGNORECASE)
    pct_m  = re.search(r'\b(?:percentage|percent|%)\s*[:\s]\s*([0-9]{2,3}(?:\.[0-9]{1,3})?)\b', text, re.IGNORECASE)

    grade = None
    label = None
    if cpi_m:
        v = float(cpi_m.group(1))
        if 0.0 < v <= 10.0:
            grade, label = str(round(v, 2)), "CPI"
    elif cgpa_m:
        v = float(cgpa_m.group(1))
        if 0.0 < v <= 10.0:
            grade, label = str(round(v, 2)), "CGPA"
    elif spi_m:
        v = float(spi_m.group(1))
        if 0.0 < v <= 10.0:
            grade, label = str(round(v, 2)), "SPI"

    pct = None
    if pct_m:
        v = float(pct_m.group(1))
        if 0.0 < v <= 100.0:
            pct = str(round(v, 2))

    return grade, label, pct


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user_id", type=int, default=None)
    parser.add_argument("--doc_type", type=str, default=None)
    parser.add_argument("--all", action="store_true", help="Reprocess ALL academic docs even if already extracted")
    args = parser.parse_args()

    from app.core.supabase_client import get_supabase
    from app.files.pdf_converter import pdf_to_image
    import cv2
    import numpy as np
    # import pytesseract
    from PIL import Image

    sb = get_supabase()
    ACADEMIC_TYPES = {"tenth", "twelfth", "diploma", "degree", "semester"}

    q = sb.table("extracted_data").select("*").in_("doc_type", list(ACADEMIC_TYPES))
    if args.user_id:
        q = q.eq("user_id", args.user_id)
    if args.doc_type:
        q = q.eq("doc_type", args.doc_type)
    if not args.all:
        # Only reprocess rows with missing grade AND missing percentage
        q = q.is_("pan_number", "null").is_("aadhaar_number", "null")

    res = q.execute()
    rows = res.data or []
    logger.info("Found %d academic rows to reprocess", len(rows))

    ok = 0
    failed = 0
    for row in rows:
        uid = row["user_id"]
        doc_type = row["doc_type"]
        storage_path = row.get("dob", "")  # repurposed column
        row_id = row["id"]

        if not storage_path:
            logger.warning("Row %s has no storage_path — skipping", row_id)
            failed += 1
            continue

        logger.info("Processing user_id=%s doc_type=%s path=%s", uid, doc_type, storage_path)
        try:
            file_bytes = sb.storage.from_("documents").download(storage_path)
            if not file_bytes:
                raise ValueError("Empty download")

            if file_bytes[:4] == b"%PDF":
                pil_img = pdf_to_image(io.BytesIO(file_bytes))
                if pil_img is None:
                    raise ValueError("pdf_to_image returned None")
            else:
                pil_img = Image.open(io.BytesIO(file_bytes)).convert("RGB")

            direct_text = pytesseract.image_to_string(pil_img, lang="eng", config="--psm 3 --oem 3")
            grade, grade_label, pct = extract_grade_from_text(direct_text)

            logger.info("  → grade=%s (%s)  pct=%s", grade, grade_label, pct)

            if grade or pct:
                update = {}
                if grade:
                    update["pan_number"] = grade      # repurposed: stores CGPA/SPI/CPI
                if pct:
                    update["aadhaar_number"] = pct    # repurposed: stores percentage
                sb.table("extracted_data").update(update).eq("id", row_id).execute()
                logger.info("  ✓ Updated row %s", row_id)
                ok += 1
            else:
                logger.warning("  ✗ No grade/pct found in %d chars of text", len(direct_text))
                failed += 1

        except Exception as e:
            logger.error("  ✗ Error for row %s: %s", row_id, e)
            failed += 1

    logger.info("Done. Success=%d  Failed=%d", ok, failed)


if __name__ == "__main__":
    main()
