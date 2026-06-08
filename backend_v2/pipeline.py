"""
pipeline.py — Layer 1: Pure Visual Line Reconstruction

PIPELINE (Layer 1 only):
  render → ocr → normalize → lines → response

NO table engine.
NO phrase merger.
NO region classifier.
NO KV parser.
NO semantic mapper.

Those belong to Layer 2 and Layer 3.
Layer 1 must be visually stable first.
"""
import time
import cv2
import logging
import pathlib

from ocr_engine       import extract_text_from_image
from pdf_renderer     import render_pdf_to_images
from layout_tree      import Document, Page
from normalizer       import normalize_boxes, normalize_paddle_result
from line_engine      import build_lines
from region_engine    import assign_regions
from response_builder import build_response
from pipeline_manager import PipelineManager, PipelineStageError

logger = logging.getLogger(__name__)

DEBUG_SAVE_IMAGES = True
PREVIEW_DIR = pathlib.Path("static/previews")
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

# OCR input size cap: preview image stays at full render resolution (1800px),
# OCR receives a slightly smaller image (faster inference, no accuracy loss at 1600px).
MAX_OCR_W = 1600


def _save(img, name):
    if DEBUG_SAVE_IMAGES:
        try:
            cv2.imwrite(str(name), img)
        except Exception as exc:
            logger.warning("debug save failed: %s — %s", name, exc)


def run_pipeline(
    file_bytes: bytes,
    filename: str,
    run_id: str = "",
    start_time: float = None,
    max_seconds: float = 600,
    progress_cb=None,
) -> dict:
    """progress_cb(msg: str) — called at each stage for frontend status updates.
    Never affects accuracy or output — purely informational."""
    total_start = start_time if start_time is not None else time.time()
    safe_id = run_id or "latest"
    manager = PipelineManager(safe_id)

    def _progress(msg: str):
        if progress_cb:
            try:
                progress_cb(msg)
            except Exception:
                pass  # never let progress reporting break the pipeline

    doc = Document(title=filename)
    preview_urls = []

    try:
        # ── 1. RENDER ─────────────────────────────────────────────────────────
        _progress("Rendering PDF…")
        def _render():
            return render_pdf_to_images(file_bytes, max_width=1800)

        pages_img = manager.execute_stage("render", _render)
        total_pages = len(pages_img)

        # MULTI-PAGE LOOP
        for page_idx, img in enumerate(pages_img):
            # Hard timeout guard
            elapsed = time.time() - total_start
            if elapsed > max_seconds:
                raise TimeoutError(
                    f"OCR timeout after {elapsed:.0f}s (limit={max_seconds}s) "
                    f"at page {page_idx + 1}/{total_pages}"
                )
            page_t0 = time.perf_counter()
            logger.info("Page %d/%d  elapsed=%.1fs", page_idx + 1, total_pages, elapsed)
            _progress(f"OCR page {page_idx + 1} of {total_pages}…")

            ph, pw = img.shape[:2]
            page_obj = Page(page_number=page_idx + 1, width=pw, height=ph)

            # Save preview for every page
            prev_path = PREVIEW_DIR / f"{safe_id}_p{page_idx}.jpg"
            _save(img, prev_path)
            preview_urls.append(f"http://127.0.0.1:8000/static/previews/{safe_id}_p{page_idx}.jpg")

            # ── 2. OCR ────────────────────────────────────────────────────────
            def _ocr():
                # Scale down for OCR only (preview already saved at full size above)
                h_img, w_img = img.shape[:2]
                if w_img > MAX_OCR_W:
                    scale_factor = MAX_OCR_W / w_img
                    ocr_img = cv2.resize(
                        img,
                        (MAX_OCR_W, int(h_img * scale_factor)),
                        interpolation=cv2.INTER_AREA,
                    )
                    print(f"[TIMING] p{page_idx}  input={w_img}x{h_img}  ocr_input={MAX_OCR_W}x{int(h_img*scale_factor)}  scale={scale_factor:.2f}")
                else:
                    ocr_img = img
                    print(f"[TIMING] p{page_idx}  input={w_img}x{h_img}  no_resize_needed")

                denoised = cv2.medianBlur(ocr_img, 3)
                _ocr_t0 = time.perf_counter()
                raw = extract_text_from_image(denoised)
                ocr_ms = int((time.perf_counter() - _ocr_t0) * 1000)
                print(f"[TIMING] p{page_idx}  ocr_inference={ocr_ms}ms")
                if raw and isinstance(raw, list) and len(raw) > 0:
                    raw = raw[0]
                return normalize_paddle_result(raw)

            boxes = manager.execute_stage(f"ocr_p{page_idx}", _ocr)

            # ── 3. NORMALIZE ──────────────────────────────────────────────────
            words = manager.execute_stage(f"normalize_p{page_idx}", normalize_boxes, boxes)

            # ── 4. LINES ──────────────────────────────────────────────────────
            # Group words by Y proximity. Sort words left→right within each line.
            # Join with spaces. Preserve coordinates.
            # THIS IS ALL WE DO. No regions. No tables. No semantics.
            lines = manager.execute_stage(f"lines_p{page_idx}", build_lines, words)

            page_obj.words = words
            page_obj.lines = lines

            # ── 5. REGIONS (Layer 2) ──────────────────────────────────────────
            manager.execute_stage(f"regions_p{page_idx}", assign_regions, page_obj)

            page_total_ms = int((time.perf_counter() - page_t0) * 1000)
            print(f"[TIMING] p{page_idx}  page_total={page_total_ms}ms  words={len(words)}")

            doc.pages.append(page_obj)

    except PipelineStageError as e:
        logger.warning("Pipeline halted early at stage: %s", e.stage)
    except Exception as e:
        logger.exception("Pipeline crash")
        manager.state["status"] = "failed"
        manager.state["error_message"] = str(e)

    # ── BUILD RESPONSE ────────────────────────────────────────────────────────
    _progress("Building layout…")
    manager.state["perf"]["total_ms"] = int((time.time() - total_start) * 1000)

    try:
        _progress("Finalizing…")
        response = build_response(doc, filename, safe_id, preview_urls, manager.state["perf"])

        response["overall_status"] = manager.state["status"]
        if manager.state["error_stage"]:
            response["error"] = (
                f"{manager.state['error_stage']} failed: {manager.state['error_message']}"
            )
        return response

    except Exception as e:
        logger.exception("Response builder failed")
        return {
            "success":        False,
            "overall_status": "failed",
            "pipeline":       "layer1_raw",
            "preview_url":    preview_urls[0] if preview_urls else "",
            "images":         {"pages": preview_urls},
            "lines":          [],
            "clean_text":     "",
            "error":          str(e),
            "perf_log":       manager.state["perf"],
        }
