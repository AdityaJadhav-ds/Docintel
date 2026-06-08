-- Migration 008: Add verification fields to users table
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_verified int DEFAULT 0;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verification_status text DEFAULT 'PENDING';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS workflow_state text DEFAULT 'UPLOADED';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS status text DEFAULT 'PENDING';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS review_status text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verified_at timestamptz;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS verified_by text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS aadhaar_number text;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS pan_number text;
