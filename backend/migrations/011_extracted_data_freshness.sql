-- Migration 011: Add processed_at column + unique constraint to extracted_data
-- ============================================================================
-- Purpose:
--   1. Ensure extracted_data has a processed_at timestamp so the API can
--      sort by recency and guarantee fresh OCR results are always displayed.
--
--   2. Add unique constraint on (user_id, doc_type) so upsert fallback
--      in validation_service works correctly. Note: we use (user_id, doc_type)
--      NOT (user_id, doc_type, version) — KYC docs always have version=1,
--      so the old version-keyed upsert never updated, it only inserted.
--
-- Safety:
--   - ADD COLUMN IF NOT EXISTS → safe on re-run
--   - CREATE INDEX IF NOT EXISTS → safe on re-run
--   - The unique constraint uses a UNIQUE INDEX rather than ALTER TABLE
--     ADD CONSTRAINT to avoid errors if rows with duplicates already exist.
--     If duplicates exist, run the cleanup step below first.
--
-- Run order: after migration 010.

-- ── Step 1: Add processed_at column if not present ───────────────────────────
ALTER TABLE extracted_data
    ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ DEFAULT NOW();

-- Backfill null rows with current time (so existing rows sort correctly)
UPDATE extracted_data
SET processed_at = NOW()
WHERE processed_at IS NULL;

-- ── Step 2: Create index for fast recency queries ─────────────────────────────
CREATE INDEX IF NOT EXISTS idx_extracted_data_user_doctype_ts
    ON extracted_data (user_id, doc_type, processed_at DESC);

-- ── Step 3: Optional — deduplicate before adding unique constraint ────────────
-- If you have duplicate (user_id, doc_type) rows, run this CTE first:
--
-- DELETE FROM extracted_data
-- WHERE id NOT IN (
--     SELECT DISTINCT ON (user_id, doc_type) id
--     FROM extracted_data
--     ORDER BY user_id, doc_type, processed_at DESC NULLS LAST
-- );

-- ── Step 4: Create unique index on (user_id, doc_type) ───────────────────────
-- This makes upsert(on_conflict="user_id,doc_type") work correctly.
-- Only run this after the deduplication step above if needed.
-- CREATE UNIQUE INDEX IF NOT EXISTS uidx_extracted_data_user_doctype
--     ON extracted_data (user_id, doc_type);

-- Note: The primary fix (DELETE+INSERT strategy in validation_service.py)
-- does NOT require this constraint — it's provided as an optional DB-level
-- enforcement layer for extra safety.
