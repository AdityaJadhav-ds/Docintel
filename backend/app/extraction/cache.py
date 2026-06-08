"""
app/extraction/cache.py
========================
Content-based OCR result cache.

Cache key = SHA256(file_bytes) + ENGINE_VERSION + PIPELINE_VERSION.

Rules:
  - Same file (same bytes) + same engine → return cached result
  - File changed (different SHA256) → cache miss → full re-extraction
  - Engine version bumped → all existing cache entries are stale → full re-extraction
  - Pipeline version bumped → all existing cache entries are stale → full re-extraction

Safety:
  - Thread-safe (threading.Lock)
  - TTL eviction (default 24h) — prevents memory leak
  - Max entries cap (default 200) — evicts LRU when full
  - Disabled by setting OCR_CACHE_ENABLED=false in .env

This cache NEVER stores base64 images (too large). It stores the
ExtractionResult.to_api_dict() output which is what the frontend
and validation pipeline consume.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Versioning — bump these when the OCR engine or pipeline logic changes ─────
# Cache entries from prior versions are automatically invalidated.
ENGINE_VERSION   = "paddleocr-3.x"
PIPELINE_VERSION = "universal-v2"

# ── Configuration ─────────────────────────────────────────────────────────────
_CACHE_ENABLED   = os.environ.get("OCR_CACHE_ENABLED", "true").lower() != "false"
_MAX_ENTRIES     = int(os.environ.get("OCR_CACHE_MAX_ENTRIES", "200"))
_TTL_SECONDS     = int(os.environ.get("OCR_CACHE_TTL_SECONDS", str(24 * 3600)))  # 24h


# ── Internal state ─────────────────────────────────────────────────────────────
_lock:  threading.Lock       = threading.Lock()
_store: OrderedDict[str, dict] = OrderedDict()  # key → {result, ts}

_hits   = 0
_misses = 0


# ── Public API ─────────────────────────────────────────────────────────────────

def make_cache_key(file_bytes: bytes) -> str:
    """
    Compute a stable cache key from the file content + engine/pipeline versions.
    Any change to the bytes or versions produces a different key.
    """
    content_hash = hashlib.sha256(file_bytes).hexdigest()
    return f"{content_hash}:{ENGINE_VERSION}:{PIPELINE_VERSION}"


def get(file_bytes: bytes) -> Optional[Dict[str, Any]]:
    """
    Return cached OCR result for this file content, or None on cache miss.
    Returns None if cache is disabled.
    """
    global _hits, _misses

    if not _CACHE_ENABLED:
        return None

    key = make_cache_key(file_bytes)
    now = time.monotonic()

    with _lock:
        entry = _store.get(key)
        if entry is None:
            _misses += 1
            logger.debug("[cache] MISS key=%s…", key[:16])
            return None

        # TTL check
        if now - entry["ts"] > _TTL_SECONDS:
            del _store[key]
            _misses += 1
            logger.debug("[cache] EXPIRED key=%s…", key[:16])
            return None

        # LRU: move to end
        _store.move_to_end(key)
        _hits += 1
        age_s = round(now - entry["ts"])
        logger.info("[cache] HIT key=%s… age=%ds hits=%d misses=%d", key[:16], age_s, _hits, _misses)
        return entry["result"]


def put(file_bytes: bytes, result: Dict[str, Any]) -> None:
    """
    Store an OCR result in the cache keyed by file content.
    No-op if cache is disabled.
    """
    if not _CACHE_ENABLED:
        return

    key = make_cache_key(file_bytes)

    with _lock:
        _store[key] = {"result": result, "ts": time.monotonic()}
        _store.move_to_end(key)

        # Evict oldest entries if over cap
        while len(_store) > _MAX_ENTRIES:
            evicted_key, _ = _store.popitem(last=False)
            logger.debug("[cache] EVICT key=%s…", evicted_key[:16])

    logger.debug("[cache] STORED key=%s… total=%d", key[:16], len(_store))


def invalidate(file_bytes: bytes) -> bool:
    """
    Explicitly invalidate the cache entry for a given file.
    Returns True if an entry was removed, False if no entry existed.
    Called when re-extraction is forced.
    """
    if not _CACHE_ENABLED:
        return False

    key = make_cache_key(file_bytes)
    with _lock:
        if key in _store:
            del _store[key]
            logger.info("[cache] INVALIDATED key=%s…", key[:16])
            return True
    return False


def invalidate_by_hash(content_hash: str) -> bool:
    """
    Invalidate all cache entries matching a given SHA256 hash
    (regardless of engine/pipeline version suffix).
    Used when re-extraction is triggered without the original bytes.
    """
    if not _CACHE_ENABLED:
        return False

    removed = 0
    with _lock:
        to_delete = [k for k in _store if k.startswith(content_hash)]
        for k in to_delete:
            del _store[k]
            removed += 1

    if removed:
        logger.info("[cache] INVALIDATED %d entries for hash=%s…", removed, content_hash[:16])
    return removed > 0


def stats() -> Dict[str, Any]:
    """Return cache statistics for health/diagnostics endpoint."""
    with _lock:
        total = len(_store)
    return {
        "enabled":  _CACHE_ENABLED,
        "entries":  total,
        "max":      _MAX_ENTRIES,
        "ttl_s":    _TTL_SECONDS,
        "hits":     _hits,
        "misses":   _misses,
        "hit_rate": round(_hits / max(_hits + _misses, 1) * 100, 1),
        "engine_version":   ENGINE_VERSION,
        "pipeline_version": PIPELINE_VERSION,
    }


def clear() -> int:
    """Clear entire cache. Returns number of entries removed."""
    with _lock:
        n = len(_store)
        _store.clear()
    logger.info("[cache] CLEARED %d entries", n)
    return n
