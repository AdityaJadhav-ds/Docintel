-- ============================================================
-- Migration 005: Fix Academic Document Relational Storage
-- DocValidator Platform
-- Run in: https://supabase.com/dashboard → SQL Editor
-- ============================================================
-- ROOT CAUSE FIX:
--   The documents table only allowed doc_type IN ('aadhaar','pan').
--   Academic uploads (tenth, twelfth, diploma, degree, semester)
--   were silently rejected by this CHECK constraint.
-- ============================================================

-- 1. DROP the old restrictive CHECK constraint on documents.doc_type
ALTER TABLE public.documents
  DROP CONSTRAINT IF EXISTS documents_doc_type_check;

-- 2. ADD a new inclusive CHECK constraint that allows academic types
ALTER TABLE public.documents
  ADD CONSTRAINT documents_doc_type_check
  CHECK (doc_type IN (
    'aadhaar', 'pan',
    'tenth', 'twelfth', 'diploma', 'degree', 'semester'
  ));

-- 3. ADD candidate_id (FK → users) to academic_documents if missing
ALTER TABLE public.academic_documents
  ADD COLUMN IF NOT EXISTS candidate_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL;

-- 4. ADD user_id alias column to academic_documents for consistency
ALTER TABLE public.academic_documents
  ADD COLUMN IF NOT EXISTS user_id BIGINT REFERENCES public.users(id) ON DELETE SET NULL;

-- 5. ADD doc_type_label to academic_documents (tenth|twelfth|diploma|degree|semester)
--    (already exists as doc_type, but ensure it's not constrained)
-- No action needed — academic_documents.doc_type is VARCHAR(50) with no CHECK constraint.

-- 6. Index for fast candidate lookups
CREATE INDEX IF NOT EXISTS idx_documents_user_doc_type
  ON public.documents(user_id, doc_type);

CREATE INDEX IF NOT EXISTS idx_academic_docs_candidate_id
  ON public.academic_documents(candidate_id);

CREATE INDEX IF NOT EXISTS idx_academic_docs_user_id
  ON public.academic_documents(user_id);

-- 7. Also fix validation_reviews — it also rejects academic doc types
ALTER TABLE public.validation_reviews
  DROP CONSTRAINT IF EXISTS validation_reviews_doc_type_check;

ALTER TABLE public.validation_reviews
  ADD CONSTRAINT validation_reviews_doc_type_check
  CHECK (doc_type IN (
    'aadhaar', 'pan', 'unknown',
    'tenth', 'twelfth', 'diploma', 'degree', 'semester'
  ));

-- ============================================================
-- VERIFY AFTER RUNNING:
--   SELECT column_name, data_type
--   FROM information_schema.columns
--   WHERE table_name = 'documents';
--
--   SELECT constraint_name, check_clause
--   FROM information_schema.check_constraints
--   WHERE constraint_name LIKE '%doc_type%';
-- ============================================================
