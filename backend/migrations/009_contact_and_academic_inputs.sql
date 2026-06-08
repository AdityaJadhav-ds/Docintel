-- ============================================================
-- Migration 009: Contact Fields + Academic Inputs on users table
-- DocValidator Platform - Entered Data Persistence Fix
-- Run in: https://supabase.com/dashboard -> SQL Editor
-- ============================================================

-- Contact info entered during registration
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS email             text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS mobile_number     text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS permanent_address text;

-- User-entered academic scores (JSON object: { tenth: {percentage:"82"}, twelfth: {...}, ... })
-- Stored as JSONB so no schema changes needed when adding new academic types
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS academic_inputs   jsonb DEFAULT '{}';

-- Indexes for email lookups (optional but useful)
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);
