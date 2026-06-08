-- Migration 010: Permanent Approval
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_verified BOOLEAN DEFAULT false;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_name TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_aadhaar TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_pan TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_dob TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_percentage TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS final_cgpa TEXT;
