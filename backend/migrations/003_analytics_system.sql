-- ============================================================
-- Migration 003: Analytics & Monitoring Tables
-- DocValidator Platform — Intelligence Layer
-- Run in: https://supabase.com/dashboard → SQL Editor
-- ============================================================

-- 1. ANALYTICS SNAPSHOTS (periodic point-in-time dashboard snapshots)
create table if not exists public.analytics_snapshots (
  id               uuid primary key default gen_random_uuid(),
  snapshot_type    text not null,   -- 'daily' | 'hourly' | 'weekly'
  period_start     timestamptz not null,
  period_end       timestamptz not null,
  metrics          jsonb not null default '{}',
  created_at       timestamptz default now()
);

-- 2. SYSTEM METRICS (API + worker performance)
create table if not exists public.system_metrics (
  id               uuid primary key default gen_random_uuid(),
  metric_name      text not null,
  metric_value     numeric(12,4) not null,
  unit             text,            -- 'ms' | 'count' | 'percent' | 'bytes'
  tags             jsonb default '{}',
  recorded_at      timestamptz default now()
);

-- 3. REVIEWER METRICS (per-reviewer performance snapshots)
create table if not exists public.reviewer_metrics (
  id               uuid primary key default gen_random_uuid(),
  reviewer_id      text not null,
  period_date      date not null,
  reviews_completed int default 0,
  reviews_approved  int default 0,
  reviews_rejected  int default 0,
  reviews_corrected int default 0,
  avg_review_time_s numeric(10,2) default 0,
  corrections_made  int default 0,
  created_at       timestamptz default now(),
  unique (reviewer_id, period_date)
);

-- 4. OCR METRICS (daily OCR performance)
create table if not exists public.ocr_metrics (
  id               uuid primary key default gen_random_uuid(),
  period_date      date not null unique,
  total_processed  int default 0,
  success_count    int default 0,
  failure_count    int default 0,
  aadhaar_count    int default 0,
  pan_count        int default 0,
  avg_confidence   numeric(5,4) default 0,
  avg_processing_ms numeric(10,2) default 0,
  fallback_used_count int default 0,
  created_at       timestamptz default now()
);

-- 5. FRAUD METRICS (daily fraud summary)
create table if not exists public.fraud_metrics (
  id               uuid primary key default gen_random_uuid(),
  period_date      date not null unique,
  total_analyzed   int default 0,
  high_risk_count  int default 0,
  critical_count   int default 0,
  duplicate_count  int default 0,
  screenshot_count int default 0,
  tamper_count     int default 0,
  avg_risk_score   numeric(5,2) default 0,
  created_at       timestamptz default now()
);

-- 6. ALERTS (operational alerts, append-only)
create table if not exists public.alerts (
  id           uuid primary key default gen_random_uuid(),
  alert_type   text not null,
  severity     text not null check (severity in ('INFO','WARNING','CRITICAL')),
  title        text not null,
  message      text not null,
  metric_name  text,
  metric_value numeric(12,4),
  threshold    numeric(12,4),
  resolved     boolean default false,
  resolved_at  timestamptz,
  created_at   timestamptz default now()
);

-- Indexes
create index if not exists idx_as_period_start   on public.analytics_snapshots(period_start desc);
create index if not exists idx_as_type           on public.analytics_snapshots(snapshot_type);
create index if not exists idx_sm_metric_name    on public.system_metrics(metric_name);
create index if not exists idx_sm_recorded_at    on public.system_metrics(recorded_at desc);
create index if not exists idx_rm_reviewer_id    on public.reviewer_metrics(reviewer_id);
create index if not exists idx_rm_period_date    on public.reviewer_metrics(period_date desc);
create index if not exists idx_ocr_period_date   on public.ocr_metrics(period_date desc);
create index if not exists idx_fm_period_date    on public.fraud_metrics(period_date desc);
create index if not exists idx_alerts_severity   on public.alerts(severity);
create index if not exists idx_alerts_resolved   on public.alerts(resolved);
create index if not exists idx_alerts_created    on public.alerts(created_at desc);
