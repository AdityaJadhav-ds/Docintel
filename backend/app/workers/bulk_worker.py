"""
app/workers/bulk_worker.py — Async bulk processing engine
==========================================================
Processes multiple users concurrently without blocking the FastAPI server.
Uses asyncio + thread pool for CPU-heavy OCR tasks.

Concurrency model (v2):
  MAX_WORKERS = 2 independent worker coroutines drain the same asyncio.Queue.
  Each coroutine calls process_user_documents_async() which runs
  process_user_documents() in asyncio's default thread pool via to_thread().

  Thread safety:
    OCR predict() is serialized via _OCR_PREDICT_LOCK in pipeline.py.
    (bench_ocr_lock.py proved 17% wall-time improvement with zero corruption.)
    All other stages — downloads, Supabase writes, review engine — run freely.

  Do NOT increase MAX_WORKERS beyond 2 without re-running bench_ocr_lock.py.
"""

from __future__ import annotations
import asyncio
from typing import List, Dict, Optional
from app.core.logger import logger
from app.core.supabase_client import get_supabase
from app.services.validation_service import process_user_documents_async

MAX_WORKERS = 2   # proven safe by bench_ocr_lock.py; OCR lock limits corruption

# ── Job queue ─────────────────────────────────────────────────────────────────

_job_queue:    asyncio.Queue       = None
_worker_tasks: List[asyncio.Task] = []


def _get_queue() -> asyncio.Queue:
    global _job_queue
    if _job_queue is None:
        _job_queue = asyncio.Queue(maxsize=1000)
    return _job_queue


async def _worker_loop(worker_id: int):
    """Background coroutine: drain the queue and process users."""
    queue = _get_queue()
    logger.info("[bulk_worker] Worker %d started.", worker_id)
    while True:
        user_id = await queue.get()
        try:
            logger.info("[bulk_worker] Worker %d processing user_id=%s", worker_id, user_id)
            result = await process_user_documents_async(user_id)
            logger.info(
                "[bulk_worker] Worker %d done user_id=%s status=%s",
                worker_id, user_id, result.get("overall_status"),
            )
        except Exception as exc:
            logger.error("[bulk_worker] Worker %d error for user_id=%s: %s", worker_id, user_id, exc)
        finally:
            queue.task_done()


async def start_worker():
    """Call once at FastAPI startup to launch MAX_WORKERS background workers."""
    global _worker_tasks
    # Kill any dead tasks from a previous startup
    _worker_tasks = [t for t in _worker_tasks if not t.done()]
    while len(_worker_tasks) < MAX_WORKERS:
        wid  = len(_worker_tasks)
        task = asyncio.create_task(_worker_loop(wid))
        _worker_tasks.append(task)
        logger.info("[bulk_worker] Started worker %d (total=%d)", wid, len(_worker_tasks))


async def enqueue_user(user_id: int) -> bool:
    """Add a user to the processing queue. Returns False if queue is full."""
    queue = _get_queue()
    try:
        queue.put_nowait(user_id)
        logger.info("[bulk_worker] Enqueued user_id=%s (queue size=%d)", user_id, queue.qsize())
        return True
    except asyncio.QueueFull:
        logger.warning("[bulk_worker] Queue full! Cannot enqueue user_id=%s", user_id)
        return False


async def enqueue_all_users() -> Dict:
    """Fetch all users and enqueue them for bulk reprocessing."""
    try:
        sb = get_supabase()
        res = sb.table("users").select("id").execute()
        users = res.data or []
    except Exception as exc:
        logger.error("[bulk_worker] Failed to fetch users: %s", exc)
        return {"success": False, "error": str(exc), "enqueued": 0}

    enqueued = 0
    skipped  = 0
    for u in users:
        success = await enqueue_user(u["id"])
        if success:
            enqueued += 1
        else:
            skipped += 1

    return {
        "success":  True,
        "total":    len(users),
        "enqueued": enqueued,
        "skipped":  skipped,
    }


def get_queue_status() -> Dict:
    """Return current queue depth and worker status."""
    q = _get_queue()
    alive = sum(1 for t in _worker_tasks if not t.done())
    return {
        "queue_size":   q.qsize(),
        "max_size":     q.maxsize,
        "max_workers":  MAX_WORKERS,
        "workers_alive": alive,
    }
