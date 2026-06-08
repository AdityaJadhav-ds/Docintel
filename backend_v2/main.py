import os
# CPU thread pinning: PaddleOCR on Windows/CPU (OpenBLAS build) is hurt by
# threads > 1.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uuid
import time
import hashlib
import logging
import pathlib

from pipeline import run_pipeline
from ocr_engine import get_ocr_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(title="DocValidator V2 — OCR Engine")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve preview images as static files
STATIC_DIR = pathlib.Path("static")
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── In-memory stores ───────────────────────────────────────────────────────────
# run_id -> result dict  (lifecycle: "running" -> "done" | "failed")
_RESULTS: dict = {}

# md5(file_bytes) -> completed result dict
# Repeat uploads of the identical file return instantly without re-running OCR.
_CACHE: dict = {}

# Hard wall-clock limit per document.
MAX_RUN_SECONDS = 600


# ── Startup: warm OCR engine ──────────────────────────────────────────────────
@app.on_event("startup")
def warmup_ocr():
    """
    Load PaddleOCR model weights at server startup so the first OCR request
    does not pay the ~15-30s model-load cost.
    """
    logger.info("WARMUP: loading OCR engine at startup...")
    t0 = time.time()
    get_ocr_engine()
    logger.info("WARMUP: OCR engine ready in %.1fs", time.time() - t0)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _file_hash(file_bytes: bytes) -> str:
    return hashlib.md5(file_bytes).hexdigest()


def _make_progress_cb(run_id: str):
    def _cb(msg: str):
        if run_id in _RESULTS and _RESULTS[run_id].get("overall_status") == "running":
            _RESULTS[run_id]["progress"] = msg
    return _cb


# ── Background worker ─────────────────────────────────────────────────────────
def _pipeline_worker(file_bytes: bytes, filename: str, run_id: str) -> None:
    """
    Runs the full PaddleOCR pipeline for one document in FastAPI's threadpool.
    Results are stored in _RESULTS[run_id] for the frontend to poll.
    No database writes — the original backend (port 8000) handles Supabase persistence.
    """
    start_time = time.time()
    result = None
    file_hash = _file_hash(file_bytes)

    logger.info("START run=%s file=%s size=%d", run_id, filename, len(file_bytes))

    try:
        # Cache hit: same file already processed this session
        if file_hash in _CACHE:
            logger.info("CACHE HIT run=%s hash=%s", run_id, file_hash[:8])
            result = dict(_CACHE[file_hash])
            result["from_cache"] = True
            result["overall_status"] = "done"
            return

        progress_cb = _make_progress_cb(run_id)
        progress_cb("Rendering PDF...")

        result = run_pipeline(
            file_bytes, filename,
            run_id=run_id,
            start_time=start_time,
            max_seconds=MAX_RUN_SECONDS,
            progress_cb=progress_cb,
        )

        if result.get("success"):
            _CACHE[file_hash] = result
            logger.info("CACHED run=%s hash=%s words=%d", run_id, file_hash[:8], result.get("word_count", 0))

    except Exception as e:
        logger.exception("Pipeline exception for run=%s", run_id)
        result = {
            "success":        False,
            "overall_status": "failed",
            "metadata":       {"filename": filename, "page_count": 0},
            "lines":          [],
            "word_count":     0,
            "error":          str(e),
        }

    finally:
        elapsed_ms = int((time.time() - start_time) * 1000)

        if result is None:
            result = {
                "success":        False,
                "overall_status": "failed",
                "error":          "Unknown crash before result assigned",
                "metadata":       {"filename": filename, "page_count": 0},
                "lines":          [],
                "word_count":     0,
                "elapsed_ms":     elapsed_ms,
            }

        result["processing_time_ms"] = elapsed_ms
        if result.get("overall_status") == "running":
            result["overall_status"] = "failed"

        _RESULTS[run_id] = result
        logger.info(
            "DONE run=%s status=%s words=%d elapsed_ms=%d",
            run_id, result.get("overall_status"),
            result.get("word_count", 0), elapsed_ms
        )


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/api/ocr/pipeline/start")
async def pipeline_start(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    """Accept upload, return run_id immediately. Pipeline runs in background."""
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Empty file")

    filename = file.filename or "document.pdf"
    run_id   = str(uuid.uuid4())

    _RESULTS[run_id] = {
        "success":        False,
        "overall_status": "running",
        "progress":       "Queued...",
        "metadata":       {"filename": filename},
    }

    background_tasks.add_task(_pipeline_worker, file_bytes, filename, run_id)
    return {"run_id": run_id, "status": "started", "filename": filename}


@app.get("/api/ocr/pipeline/status/{run_id}")
async def pipeline_status(run_id: str):
    if run_id not in _RESULTS:
        raise HTTPException(404, "Run not found")
    res = _RESULTS[run_id]
    status = res.get("overall_status", "running")
    return {
        "overall_status": status,
        "ready": status != "running",
        "progress": res.get("progress", ""),
    }


@app.get("/api/ocr/pipeline/result/{run_id}")
async def pipeline_result(run_id: str):
    if run_id not in _RESULTS:
        raise HTTPException(404, "Run not found")
    res = _RESULTS[run_id]
    return {
        "ready": True,
        "overall_status": res.get("overall_status", "running"),
        "result": res,
    }


@app.get("/api/health")
async def health():
    active = sum(1 for r in _RESULTS.values() if r.get("overall_status") == "running")
    return {
        "status":       "ok",
        "service":      "backend_v2_ocr",
        "active_runs":  active,
        "cached_files": len(_CACHE),
    }
