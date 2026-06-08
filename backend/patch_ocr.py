import sys, re

with open('app/services/ocr_pipeline.py', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r'def _run_region_fallback\(.*?\)\s*->\s*Dict:.*?return merged'

replacement = '''def _run_region_fallback(image_arr: np.ndarray, doc_type: str, existing_extracted: Dict) -> Dict:
    """
    Low-confidence fallback with Targeted Region OCR + Ensemble Scoring:
    1. Run OCR on document-specific cropped regions.
    2. Extract specific fields from those region texts.
    3. Merge targeted results with existing extraction using ensemble confidence.
    """
    logger.warning(
        "[ocr_pipeline] Confidence below %.0f%% — triggering TARGETED fallback for %s",
        LOW_CONFIDENCE_THRESHOLD * 100, doc_type
    )

    regions = _crop_regions(image_arr, doc_type)
    if not regions:
        return existing_extracted

    fallback_extracted = {}
    
    for region_name, region_arr in regions.items():
        try:
            r_variants = generate_variants(region_arr)
            r_ocr = run_ocr_on_variants(r_variants)
            if r_ocr.get("merged_text"):
                text = r_ocr["merged_text"]
                logger.debug("[ocr_pipeline] Region '%s': %d chars", region_name, len(text))
                
                # Targeted Parse
                if doc_type == "aadhaar":
                    parsed = parse_aadhaar(text)
                    if "name" in region_name and parsed.get("name"):
                        fallback_extracted["name"] = parsed["name"]
                    if "id" in region_name and parsed.get("aadhaar_number"):
                        fallback_extracted["aadhaar_number"] = parsed["aadhaar_number"]
                        if parsed.get("dob"):
                            fallback_extracted["dob"] = parsed["dob"]
                elif doc_type == "pan":
                    parsed = parse_pan(text)
                    if "name" in region_name and parsed.get("name"):
                        fallback_extracted["name"] = parsed["name"]
                        if parsed.get("dob"):
                            fallback_extracted["dob"] = parsed["dob"]
                    if "id" in region_name and parsed.get("pan_number"):
                        fallback_extracted["pan_number"] = parsed["pan_number"]
        except Exception as exc:
            logger.debug("[ocr_pipeline] Region '%s' failed: %s", region_name, exc)

    # Merge: Ensemble Voting
    merged = dict(existing_extracted)
    for key, value in fallback_extracted.items():
        if key in ("confidence", "field_confidences"):
            continue
        if value is not None and merged.get(key) is None:
            logger.info("[ocr_pipeline] Fallback ENSEMBLE overwriting '%s': None -> %s", key, value)
            merged[key] = value

    # Recalculate confidence
    id_field = "aadhaar_number" if doc_type == "aadhaar" else "pan_number"
    fields = ["name", id_field, "dob"]
    found = sum(1 for f in fields if merged.get(f))
    merged["confidence"] = round(found / 3.0, 4)
    logger.info("[ocr_pipeline] After targeted fallback — confidence=%.3f", merged["confidence"])

    return merged'''

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
if new_content == content:
    print('Failed to replace.')
else:
    with open('app/services/ocr_pipeline.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Successfully updated _run_region_fallback.')
