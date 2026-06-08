-- ============================================================
-- Migration 002: Fraud Detection & Risk Intelligence Tables
-- DocValidator Platform — Enterprise Risk Layer
-- Run in: https://supabase.com/dashboard → SQL Editor
-- ============================================================

-- 1. IMAGE HASHES (perceptual dedup fingerprints)
create table if not exists public.image_hashes (
  id           uuid primary key default gen_random_uuid(),
  user_id      bigint references public.users(id) on delete cascade,
  document_id  bigint references public.documents(id) on delete cascade,
  doc_type     text,
  phash        text not null,       -- perceptual hash (hex)
  ahash        text not null,       -- average hash
  dhash        text not null,       -- difference hash
  file_size_kb numeric(10,2),
  width_px     int,
  height_px    int,
  created_at   timestamptz default now()
);

-- 2. FRAUD ANALYSIS (one record per document analysis run)
create table if not exists public.fraud_analysis (
  id                  uuid primary key default gen_random_uuid(),
  user_id             bigint references public.users(id) on delete cascade,
  document_id         bigint references public.documents(id) on delete cascade,
  doc_type            text,

  -- Quality
  quality_score       int default 0 check (quality_score between 0 and 100),
  blur_score          numeric(6,2) default 0,
  brightness_score    numeric(6,2) default 0,
  contrast_score      numeric(6,2) default 0,
  noise_score         numeric(6,2) default 0,
  quality_flags       jsonb default '[]',

  -- Tamper
  tamper_score        int default 0 check (tamper_score between 0 and 100),
  tamper_flags        jsonb default '[]',

  -- Duplicate
  duplicate_detected  boolean default false,
  duplicate_score     int default 0,
  duplicate_matches   jsonb default '[]',

  -- Metadata
  metadata_flags      jsonb default '[]',
  is_screenshot       boolean default false,
  has_exif            boolean default false,
  exif_software       text,

  -- Risk
  risk_score          int default 0 check (risk_score between 0 and 100),
  risk_level          text default 'LOW_RISK'
                        check (risk_level in ('LOW_RISK','MEDIUM_RISK','HIGH_RISK','CRITICAL_RISK')),
  recommendation      text,
  risk_breakdown      jsonb default '{}',

  -- Audit
  analyzed_at         timestamptz default now(),
  created_at          timestamptz default now()
);

-- 3. DUPLICATE MATCHES (cross-user identity collision log)
create table if not exists public.duplicate_matches (
  id               uuid primary key default gen_random_uuid(),
  source_user_id   bigint references public.users(id),
  target_user_id   bigint references public.users(id),
  match_type       text not null,   -- IMAGE_HASH | AADHAAR_NUMBER | PAN_NUMBER
  match_field      text,            -- which field matched
  similarity_score int default 100, -- 0-100
  source_hash      text,
  target_hash      text,
  flagged_at       timestamptz default now()
);

-- 4. RISK SCORES (timeline — one row per analysis, immutable)
create table if not exists public.risk_scores (
  id              uuid primary key default gen_random_uuid(),
  fraud_analysis_id uuid references public.fraud_analysis(id) on delete cascade,
  user_id         bigint references public.users(id),
  document_id     bigint references public.documents(id),
  risk_score      int not null,
  risk_level      text not null,
  component_scores jsonb default '{}',
  created_at      timestamptz default now()
);

-- 5. TAMPER FLAGS (detailed tamper evidence log)
create table if not exists public.tamper_flags (
  id             uuid primary key default gen_random_uuid(),
  fraud_id       uuid references public.fraud_analysis(id) on delete cascade,
  flag_type      text not null,
  severity       text not null check (severity in ('low','medium','high')),
  description    text,
  region         jsonb default '{}',   -- optional bounding region
  confidence     int default 50,
  created_at     timestamptz default now()
);

-- 6. Indexes
create index if not exists idx_fa_user_id      on public.fraud_analysis(user_id);
create index if not exists idx_fa_risk_level   on public.fraud_analysis(risk_level);
create index if not exists idx_fa_duplicate    on public.fraud_analysis(duplicate_detected);
create index if not exists idx_ih_phash        on public.image_hashes(phash);
create index if not exists idx_ih_user_id      on public.image_hashes(user_id);
create index if not exists idx_dm_source       on public.duplicate_matches(source_user_id);
create index if not exists idx_dm_match_type   on public.duplicate_matches(match_type);
create index if not exists idx_rs_user_id      on public.risk_scores(user_id);

-- 7. Risk dashboard view
create or replace view public.fraud_risk_dashboard as
  select
    fa.id,
    fa.user_id,
    fa.doc_type,
    fa.risk_score,
    fa.risk_level,
    fa.quality_score,
    fa.tamper_score,
    fa.duplicate_detected,
    fa.is_screenshot,
    fa.recommendation,
    fa.analyzed_at,
    u.full_name as user_full_name
  from public.fraud_analysis fa
  join public.users u on u.id = fa.user_id
  order by fa.risk_score desc, fa.analyzed_at desc;
