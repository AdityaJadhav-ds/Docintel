-- ============================================================
-- Migration 006: Verify and Definitively Fix Academic Storage
-- DocValidator Platform
-- Run in: https://supabase.com/dashboard → SQL Editor
-- ============================================================
-- PURPOSE:
--   1. Drop + recreate the documents.doc_type CHECK constraint
--      to guarantee academic types are allowed.
--   2. Ensure documents table index exists for fast lookups.
--   3. Verification queries at the end to confirm everything works.
-- ============================================================

-- STEP 1: Drop the old constraint (if it exists in any form)
ALTER TABLE public.documents
  DROP CONSTRAINT IF EXISTS documents_doc_type_check;

-- STEP 2: Add the inclusive constraint covering all academic types
ALTER TABLE public.documents
  ADD CONSTRAINT documents_doc_type_check
  CHECK (doc_type IN (
    'aadhaar', 'pan',
    'tenth', 'twelfth', 'diploma', 'degree', 'semester'
  ));

-- STEP 3: Ensure index exists for fast candidate lookups
CREATE INDEX IF NOT EXISTS idx_documents_user_id
  ON public.documents(user_id);

CREATE INDEX IF NOT EXISTS idx_documents_user_doc_type
  ON public.documents(user_id, doc_type);

-- STEP 4: Fix validation_reviews constraint if it exists
ALTER TABLE public.validation_reviews
  DROP CONSTRAINT IF EXISTS validation_reviews_doc_type_check;

-- (Ignore error if validation_reviews doesn't exist — it's fine)

-- ============================================================
-- VERIFICATION — Run these SELECT queries AFTER the ALTER TABLE
-- ============================================================

-- Check the constraint is correctly installed
SELECT constraint_name, check_clause
FROM information_schema.check_constraints
WHERE constraint_name LIKE '%doc_type%'
  AND constraint_schema = 'public';

-- Verify all uploaded doc types in documents table
SELECT doc_type, COUNT(*) as count
FROM public.documents
GROUP BY doc_type
ORDER BY count DESC;

-- Show all academic documents with their linked user_id
SELECT id, user_id, doc_type, storage_path, uploaded_at
FROM public.documents
WHERE doc_type IN ('tenth', 'twelfth', 'diploma', 'degree', 'semester')
ORDER BY uploaded_at DESC
LIMIT 50;

-- ============================================================
-- EXPECTED RESULT after uploading academic docs:
--   user_id | doc_type
--   160     | tenth
--   160     | twelfth
--   160     | degree
-- ============================================================
