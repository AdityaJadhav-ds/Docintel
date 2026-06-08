with open("app/extraction/core_extractor.py", "r", encoding="utf-8") as f:
    lines = f.read().splitlines()

# find where it broke
broken_index = lines.index("    # Falls back to 'scanned_pdf' for the generic Tesseract path.")

head = lines[:broken_index]

tail = """        "layout_meta":    layout_meta,
        "debug_pipeline": debug_pipeline,
        "doc_graph": {
            "links":                   doc_graph.get("links", []),
            "page_node":               doc_graph.get("page_node", {}),
            "stats":                   doc_graph.get("stats", {}),
            "reading_flow_confidence": reading_flow_confidence,
        },
    }




# ── Pipeline B: Scanned PDF ───────────────────────────────────────────────────



def extract_scanned_pdf(pdf_bytes: bytes, dpi: int = 250, lang: str = "auto", run_id: Optional[str] = None) -> ExtractionResult:
    \"\"\"PIPELINE B: Render PDF pages -> Fast Scanned Pipeline -> Fallback to Region-First Extraction\"\"\"
    import fitz, traceback
    from app.extraction.adaptive_scanned_pipeline import extract_adaptive_scanned_bank_statement
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mat = fitz.Matrix(dpi/72.0, dpi/72.0)

    pages, blocks, images, page_boxes, all_tables = [], [], [], [], []
    lang = lang if lang not in ("auto", "auto_detect", "", None) else "eng"
    
    from app.extraction.pipeline_state import get_run
    run_obj = get_run(run_id) if run_id else None

    local_doc_graph = {}
    doc_graph = {}

    for page_idx, page in enumerate(doc):
        if run_obj:
            run_obj.start_stage("processing", f"Processing page {page_idx+1}/{doc.page_count}")
        try:
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

            fast_res = extract_adaptive_scanned_bank_statement(bgr, page_idx)
            if fast_res.get("success"):
                logger.info(
                    "[PipelineB] Adaptive OK page=%d bank=%s handler=%s layout=%s words=%d",
                    page_idx, fast_res.get("bank_tag", "?"),
                    fast_res.get("handler", "?"),
                    fast_res.get("layout_type", "?"),
                    len(fast_res.get("clean_text", "").split()),
                )
                pages.append(fast_res.get("clean_text", ""))
                blocks.extend(fast_res.get("text_blocks", []))
                images.append(_bgr_to_b64(bgr))
                page_boxes.append(fast_res.get("text_blocks", []))
                all_tables.extend(fast_res.get("tables", []))

                if page_idx == 0:
                    doc_graph["bank_tag"]    = fast_res.get("bank_tag", "UNKNOWN")
                    doc_graph["bank_header"] = fast_res.get("header", {})
                    doc_graph["bank_tables"] = fast_res.get("tables", [])
                    doc_graph["handler"]     = fast_res.get("handler", "GenericHandler")
                    doc_graph["bank"]        = fast_res.get("bank_tag", "")
                    doc_graph["pipeline_used"] = "adaptive_bank_statement"
                    local_doc_graph.update(doc_graph)

                if run_obj:
                    run_obj.result = {
                        "success": True,
                        "document_type": "bank_statement" if local_doc_graph.get("bank_tag") else "unknown",
                        "bank": local_doc_graph.get("bank_tag", ""),
                        "header": local_doc_graph.get("bank_header", {}),
                        "tables": all_tables,
                        "text_blocks": blocks,
                        "clean_text": "\\n".join(pages),
                        "images": {"pages": images, "original": images[0] if images else ""},
                        "page_count": len(pages),
                        "blocks": blocks,
                        "tables_found": len(all_tables)
                    }
                    run_obj.has_partial_result = True

                continue

            res = _run_region_first_pipeline(bgr, page_idx, lang, is_mobile=False)
            pages.append(res["text"])
            blocks.extend(res["blocks"])
            images.append(res["image_b64"])
            page_boxes.append(res["lboxes"])
            all_tables.extend(res["tables"])
            if page_idx == 0:
                doc_graph = res.get("doc_graph", {})
                local_doc_graph.update(doc_graph)
                debug_pipeline_snapshot = res.get("debug_pipeline", {})
                
            if run_obj:
                run_obj.result = {
                    "success": True,
                    "document_type": "bank_statement" if local_doc_graph.get("bank_tag") else "unknown",
                    "bank": local_doc_graph.get("bank_tag", ""),
                    "header": local_doc_graph.get("bank_header", {}),
                    "tables": all_tables,
                    "text_blocks": blocks,
                    "clean_text": "\\n".join(pages),
                    "images": {"pages": images, "original": images[0] if images else ""},
                    "page_count": len(pages),
                    "blocks": blocks,
                    "tables_found": len(all_tables)
                }
                run_obj.has_partial_result = True

        except Exception as e:
            logger.error(
                "[PipelineB] Page %d CRASHED: %s\\n%s",
                page_idx, e, traceback.format_exc()
            )
            _fallback_text = ""
            _fallback_lboxes = []
            _fallback_image = ""
            try:
                pix2 = page.get_pixmap(matrix=fitz.Matrix(200/72, 200/72), colorspace=fitz.csRGB)
                img2 = np.frombuffer(pix2.samples, dtype=np.uint8).reshape(pix2.h, pix2.w, 3)
                bgr2 = cv2.cvtColor(img2, cv2.COLOR_RGB2BGR)
                _fallback_image = _bgr_to_b64(bgr2)
                from app.extraction.ocr_router import ocr_full_page
                fp = ocr_full_page(bgr2, mode="standard", lang=lang)
                _fallback_text = fp.get("text", "")
                _ph, _pw = bgr2.shape[:2]
                for fb in fp.get("line_boxes", []):
                    bb = fb.get("bbox", [[0,0],[0,0],[0,0],[0,0]])
                    x1,y1 = bb[0]; x2,y2 = bb[2]
                    _fallback_lboxes.append({
                        "text": fb.get("text","")[:500],
                        "confidence": round(fb.get("confidence",0.5),3),
                        "bbox": bb,
                        "nx1": x1/_pw, "ny1": y1/_ph, "nx2": x2/_pw, "ny2": y2/_ph,
                        "engine": "crash_recovery_fullpage",
                        "lang": lang, "block_type": "TEXT",
                        "semantic_zone": "TEXT", "reading_order": 0,
                        "merge_rejections": [], "quality_state": "accept",
                        "discard_reasons": [], "is_provisional": False,
                        "has_warnings": False, "discarded": False,
                    })
                logger.info("[PipelineB] Crash recovery yielded %d words on page %d",
                            len(_fallback_text.split()), page_idx)
            except Exception as _e2:
                logger.error("[PipelineB] Crash recovery also failed on page %d: %s", page_idx, _e2)

            pages.append(_fallback_text)
            page_boxes.append(_fallback_lboxes)
            images.append(_fallback_image)

    doc.close()
    full_text = "\\n\\n".join(p for p in pages if p)

    # ══ STEP 8 API-LEVEL DEBUG: PIPELINE B RESULT ═══════════════════
    print(f"[DEBUG STEP8 API] PIPELINE B RESULT:")
    print(f"[DEBUG STEP8 API]   pages={len(pages)} total_page_boxes={sum(len(pb) for pb in page_boxes)}")
    print(f"[DEBUG STEP8 API]   total_words={len(full_text.split())} blocks={len(blocks)}")
    # ════════════════════════════════════════════════════════════════════

    _final_doc_graph = locals().get("doc_graph", {})
    _dbg_snap = locals().get("debug_pipeline_snapshot", {})

"""

new_content = "\n".join(head) + "\n" + tail + "\n".join(lines[broken_index:])

with open("app/extraction/core_extractor.py", "w", encoding="utf-8") as f:
    f.write(new_content)
