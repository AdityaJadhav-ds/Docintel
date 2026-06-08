"""
app/core/database.py  —  COMPATIBILITY SHIM
=============================================
database.py was removed as part of the SQLite → Supabase migration.

This shim provides the same public API surface that was previously
exported by the SQLite-backed database.py so that the rest of main.py
(audit_service.py, query_engine.py, ocr_controller.py, ocr_job_engine.py)
continues to import without errors during the incremental migration.

IMPLEMENTATION:
  - get_connection()   → NOT supported (raises RuntimeError); callers in
                          main.py that still use raw SQL must be updated.
  - All user-facing helpers are re-routed through Supabase via
    user_service.py / supabase_client.py.
  - Audit / OCR status tables are backed by Supabase directly.

MIGRATION STATUS:
  ✅  user CRUD          → user_service.py  (Supabase)
  ✅  document storage   → document_service.py  (Supabase Storage)
  ✅  OCR results        → ocr_service.py  (Supabase extracted_data/verified_data)
  ⚠️  query_engine       → still uses get_connection(); needs Supabase port
  ⚠️  audit_service      → still uses get_connection(); needs Supabase port
  ⚠️  ocr_job_engine     → still uses get_connection(); needs Supabase port
  ⚠️  ocr_controller     → still uses get_connection(); needs Supabase port
"""

import contextlib
import sqlite3
import os
import threading
from datetime import datetime
from app.core.logger import logger

# ── Locate or create an in-process SQLite file for legacy code ONLY ────────────
# This exists purely to keep legacy services alive during migration.
# New code must NEVER use this.
_BASE_DIR  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DB_PATH   = os.path.join(_BASE_DIR, "data", "validator.db")
_db_lock   = threading.Lock()

os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)


@contextlib.contextmanager
def get_connection():
    """
    LEGACY: Returns a raw SQLite connection for code not yet ported to Supabase.
    New code must use get_supabase() from app.core.supabase_client instead.
    """
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── DB bootstrap ───────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all SQLite tables required by legacy services."""
    try:
        with get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    name TEXT, aadhaar TEXT, pan TEXT, dob TEXT,
                    status TEXT DEFAULT 'UPLOADED',
                    workflow_state TEXT DEFAULT 'UPLOADED',
                    processing_status TEXT DEFAULT 'DONE',
                    processing_result TEXT,
                    processing_at TEXT,
                    original_name TEXT, original_aadhaar TEXT, original_pan TEXT,
                    extracted_name TEXT, extracted_aadhaar TEXT, extracted_pan TEXT,
                    extracted_dob TEXT,
                    final_name TEXT, final_aadhaar TEXT, final_pan TEXT, final_dob TEXT,
                    confidence REAL DEFAULT 0.0,
                    name_status TEXT, aadhaar_status TEXT, pan_status TEXT, dob_status TEXT,
                    ocr_processed INTEGER DEFAULT 0,
                    is_verified INTEGER DEFAULT 0,
                    aadhaar_file_hash TEXT, pan_file_hash TEXT,
                    aadhaar_version INTEGER DEFAULT 1, pan_version INTEGER DEFAULT 1,
                    aadhaar_ocr_status TEXT DEFAULT 'pending',
                    pan_ocr_status TEXT DEFAULT 'pending',
                    aadhaar_ocr_version INTEGER DEFAULT 0,
                    pan_ocr_version INTEGER DEFAULT 0,
                    aadhaar_ocr_attempts INTEGER DEFAULT 0,
                    pan_ocr_attempts INTEGER DEFAULT 0,
                    last_aadhaar_ocr_at TEXT, last_pan_ocr_at TEXT,
                    uploaded_at TEXT, created_at TEXT, processing_started_at TEXT,
                    corrected_at TEXT, approved_at TEXT
                );
                CREATE TABLE IF NOT EXISTS system_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT DEFAULT 'reviewer'
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    entity_id TEXT,
                    entity_type TEXT,
                    actor_id TEXT,
                    previous_state TEXT,
                    new_state TEXT,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS ocr_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    doc_version INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT 'queued',
                    started_at TEXT,
                    completed_at TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                );
            """)
        logger.info("[database-shim] Legacy SQLite DB initialized at %s", _DB_PATH)
    except Exception as e:
        logger.error("[database-shim] init_db failed: %s", e)


# ── User helpers (SQLite-backed; used only by un-ported parts of main.py) ──────

def get_all_users() -> list:
    """Return all user rows from SQLite legacy DB."""
    try:
        with get_connection() as conn:
            rows = conn.execute("SELECT * FROM users").fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error("[database-shim] get_all_users error: %s", e)
        return []


def insert_user(user_data: dict) -> bool:
    """Insert a user row into SQLite. Returns True on success."""
    uid = user_data.get("id") or user_data.get("user_id")
    if not uid:
        return False
    try:
        with get_connection() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO users
                (id, name, aadhaar, pan, dob, status, workflow_state,
                 original_name, original_aadhaar, original_pan,
                 uploaded_at, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid,
                user_data.get("name", ""),
                user_data.get("aadhaar", ""),
                user_data.get("pan", ""),
                user_data.get("dob", ""),
                user_data.get("status", "UPLOADED"),
                user_data.get("workflow_state", "UPLOADED"),
                user_data.get("name", ""),
                user_data.get("aadhaar", ""),
                user_data.get("pan", ""),
                datetime.now().isoformat(),
                datetime.now().isoformat(),
            ))
        return True
    except Exception as e:
        logger.error("[database-shim] insert_user error: %s", e)
        return False


def check_duplicate(field: str, value: str, current_id: str = None) -> bool:
    """Return True if another user with the same field value exists."""
    try:
        with get_connection() as conn:
            if current_id:
                row = conn.execute(
                    f"SELECT id FROM users WHERE {field}=? AND id!=?",
                    (value, current_id)
                ).fetchone()
            else:
                row = conn.execute(
                    f"SELECT id FROM users WHERE {field}=?", (value,)
                ).fetchone()
            return row is not None
    except Exception as e:
        logger.error("[database-shim] check_duplicate error: %s", e)
        return False


def update_user_workflow_state(user_id: str, state: str) -> None:
    """Update the workflow_state column for a user."""
    try:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET workflow_state=?, status=? WHERE id=?",
                (state, state, user_id)
            )
    except Exception as e:
        logger.error("[database-shim] update_user_workflow_state error: %s", e)


def update_user_correction(
    user_id: str, action: str, corrected_data: dict,
    corrected_at: str, confidence: float
) -> bool:
    """Persist a reviewer correction into the SQLite DB."""
    try:
        final = {
            "final_name":    corrected_data.get("name"),
            "final_aadhaar": corrected_data.get("aadhaar"),
            "final_pan":     corrected_data.get("pan"),
            "final_dob":     corrected_data.get("dob"),
        }
        with get_connection() as conn:
            conn.execute("""
                UPDATE users SET
                    status=?, workflow_state=?, is_verified=1,
                    original_name=?, aadhaar_number=?, pan_number=?, dob=?,
                    final_name=?, final_aadhaar=?, final_pan=?, final_dob=?,
                    confidence=?, corrected_at=?, approved_at=?
                WHERE id=?
            """, (
                'verified', 'verified',
                final["final_name"], final["final_aadhaar"], final["final_pan"], final["final_dob"],
                final["final_name"], final["final_aadhaar"],
                final["final_pan"],  final["final_dob"],
                confidence, corrected_at, corrected_at, user_id,
            ))
        return True
    except Exception as e:
        logger.error("[database-shim] update_user_correction error: %s", e)
        return False


def get_system_user_by_username(username: str) -> dict | None:
    """Fetch a system (admin/reviewer) user by username."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM system_users WHERE username=?", (username,)
            ).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error("[database-shim] get_system_user_by_username error: %s", e)
        return None


# ── Bootstrap on first import ──────────────────────────────────────────────────
init_db()
