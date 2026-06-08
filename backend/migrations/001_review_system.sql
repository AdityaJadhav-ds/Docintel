-- ============================================================
-- Migration 001: Review & Audit System Tables
-- DocValidator Platform — Human Review Layer
-- Run in: https://supabase.com/dashboard → SQL Editor
-- ============================================================

-- 1. VALIDATION REVIEWS (main review record per document per run)
create table if not exists public.validation_reviews (
  id              uuid primary key default gen_random_uuid(),
  user_id         bigint not null references public.users(id) on delete cascade,
  document_id     bigint references public.documents(id) on delete set null,
  doc_type        text not null check (doc_type in ('aadhaar','pan','unknown')),

  -- OCR & match data (snapshot at time of review creation)
  ocr_confidence  numeric(5,4) default 0,
  validation_result jsonb not null default '{}',   -- full field comparison payload

  -- Decision engine output
  decision        text not null default 'REVIEW_REQUIRED'
                    check (decision in ('AUTO_APPROVED','REVIEW_REQUIRED','AUTO_REJECTED')),
  priority        int not null default 2,           -- 1=HIGH, 2=MEDIUM, 3=LOW
  decision_reasons jsonb default '[]',              -- list of rule reasons

  -- Queue status lifecycle
  status          text not null default 'pending'
                    check (status in (
                      'pending','in_review','approved','rejected',
                      'corrected','reprocess_requested','reprocessing'
                    )),

  -- Review outcome
  reviewer_id     text,                             -- auth UID of reviewer
  reviewer_notes  text,
  reviewed_at     timestamptz,

  -- Timestamps
  created_at      timestamptz default now(),
  updated_at      timestamptz default now()
);

-- 2. REVIEW HISTORY (immutable append-only audit log)
create table if not exists public.review_history (
  id          uuid primary key default gen_random_uuid(),
  review_id   uuid not null references public.validation_reviews(id) on delete cascade,
  action      text not null,           -- CREATED|APPROVED|REJECTED|CORRECTED|REPROCESS_REQUESTED|STATUS_CHANGED
  actor_id    text,                    -- reviewer UID or 'system'
  before_state jsonb default '{}',
  after_state  jsonb default '{}',
  reason      text,
  metadata    jsonb default '{}',
  created_at  timestamptz default now()
);

-- 3. CORRECTION LOGS (field-level before/after)
create table if not exists public.correction_logs (
  id              uuid primary key default gen_random_uuid(),
  review_id       uuid not null references public.validation_reviews(id) on delete cascade,
  user_id         bigint references public.users(id),
  field           text not null,       -- name | dob | aadhaar_number | pan_number
  old_value       text,
  new_value       text,
  correction_type text,                -- MANUAL_EDIT | AUTO_SUGGEST_ACCEPTED | SYSTEM_FIX
  confidence_before int,
  confidence_after  int,
  corrected_by    text,                -- reviewer UID or 'system'
  created_at      timestamptz default now()
);

-- 4. REVIEW QUEUE VIEW (convenience — pending + in_review, priority ordered)
create or replace view public.review_queue_view as
  select
    vr.id,
    vr.user_id,
    vr.doc_type,
    vr.document_id,
    vr.ocr_confidence,
    vr.decision,
    vr.priority,
    vr.status,
    vr.reviewer_id,
    vr.created_at,
    vr.updated_at,
    u.full_name as user_full_name,
    u.dob       as user_dob,
    (vr.validation_result->>'overall_status') as overall_status,
    (vr.validation_result->>'summary')        as summary
  from public.validation_reviews vr
  join public.users u on u.id = vr.user_id
  where vr.status in ('pending','in_review')
  order by vr.priority asc, vr.created_at asc;

-- 5. Indexes for performance
create index if not exists idx_vr_user_id      on public.validation_reviews(user_id);
create index if not exists idx_vr_status       on public.validation_reviews(status);
create index if not exists idx_vr_decision     on public.validation_reviews(decision);
create index if not exists idx_vr_priority     on public.validation_reviews(priority);
create index if not exists idx_vr_created_at   on public.validation_reviews(created_at desc);
create index if not exists idx_rh_review_id    on public.review_history(review_id);
create index if not exists idx_cl_review_id    on public.correction_logs(review_id);
create index if not exists idx_cl_user_id      on public.correction_logs(user_id);
