-- DocValidator Platform — Complete Database Schema
-- Run this ONCE in: https://supabase.com/dashboard/project/ymzuecxzgvamlbqhlnqs/sql/new
-- ============================================================

-- 1. USERS
create table if not exists public.users (
  id         bigserial primary key,
  full_name  text not null,
  dob        text not null,
  created_at timestamptz default now()
);

-- 2. DOCUMENTS
create table if not exists public.documents (
  id           bigserial primary key,
  user_id      bigint not null references public.users(id) on delete cascade,
  doc_type     text not null check (doc_type in ('aadhaar','pan')),
  version      int  not null default 1,
  storage_path text not null,
  uploaded_at  timestamptz default now()
);

-- 3. OCR JOBS
create table if not exists public.ocr_jobs (
  id            uuid primary key default gen_random_uuid(),
  document_id   bigint references public.documents(id) on delete cascade,
  user_id       bigint references public.users(id) on delete cascade,
  doc_type      text,
  doc_version   int  default 1,
  status        text not null default 'pending'
                  check (status in ('pending','processing','completed','failed')),
  started_at    timestamptz,
  completed_at  timestamptz,
  error_message text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- 4. EXTRACTED DATA (OCR results)
create table if not exists public.extracted_data (
  id               bigserial primary key,
  user_id          bigint references public.users(id) on delete cascade,
  doc_type         text,
  version          int default 1,
  name             text,
  aadhaar_number   text,
  pan_number       text,
  dob              text,
  confidence_score numeric(5,4) default 0,
  processed_at     timestamptz default now(),
  unique (user_id, doc_type, version)
);

-- 5. VERIFIED DATA (human review results)
create table if not exists public.verified_data (
  id          bigserial primary key,
  user_id     bigint references public.users(id) on delete cascade,
  doc_type    text,
  version     int default 1,
  status      text default 'PENDING',
  name_match  boolean default false,
  id_match    boolean default false,
  dob_match   boolean default false,
  verified_at timestamptz default now(),
  unique (user_id, doc_type, version)
);

-- 6. STORAGE BUCKET (run this separately if needed)
-- insert into storage.buckets (id, name, public)
-- values ('documents', 'documents', false)
-- on conflict (id) do nothing;
