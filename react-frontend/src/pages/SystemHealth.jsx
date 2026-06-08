import React, { useState, useEffect, useCallback } from 'react';
import Navbar from '../components/Navbar';
import { apiGetHealth, apiGetProgress } from '../api/api';
import {
  Activity, Server, Database, Layers, Clock,
  AlertTriangle, Zap, CheckCircle2, RefreshCw, Wifi, WifiOff,
} from 'lucide-react';

/* ─── pulse dot ── */
const StatusPulse = ({ color }) => (
  <div style={{ position: 'relative', width: 12, height: 12, flexShrink: 0 }}>
    <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: color, animation: 'ping 2s cubic-bezier(0,0,0.2,1) infinite', opacity: 0.5 }} />
    <div style={{ position: 'relative', width: 12, height: 12, borderRadius: '50%', background: color }} />
  </div>
);

/* ─── map health data → card display ── */
function buildStatusCards(health) {
  const sb   = health?.supabase  === 'connected';
  const wrk  = health?.workers   === 'running';
  const env  = health?.env_loaded;
  const api  = health?.status    === 'ok' || health?.status === 'degraded';

  return [
    {
      label:  'API Status',
      icon:   Server,
      status: api  ? (health.status === 'ok' ? 'Healthy' : 'Degraded') : 'Offline',
      color:  api  ? (health.status === 'ok' ? '#16A34A' : '#D97706')   : '#DC2626',
      bg:     api  ? (health.status === 'ok' ? '#DCFCE7' : '#FEF3C7')   : '#FEE2E2',
    },
    {
      label:  'OCR Engine',
      icon:   Zap,
      status: wrk ? 'Running' : 'Stopped',
      color:  wrk ? '#16A34A' : '#DC2626',
      bg:     wrk ? '#DCFCE7' : '#FEE2E2',
    },
    {
      label:  'Database',
      icon:   Database,
      status: sb  ? 'Connected' : 'Disconnected',
      color:  sb  ? '#16A34A'   : '#DC2626',
      bg:     sb  ? '#DCFCE7'   : '#FEE2E2',
    },
    {
      label:  'Env / Config',
      icon:   Layers,
      status: env ? 'Loaded' : 'Missing',
      color:  env ? '#16A34A' : '#DC2626',
      bg:     env ? '#DCFCE7' : '#FEE2E2',
    },
  ];
}

/* ─── derive system events from live data ── */
function buildEvents(health, progress) {
  const events = [];
  const now = new Date();
  const ts = (s) => {
    const d = new Date(now - s * 1000);
    return `${d.getHours().toString().padStart(2,'0')}:${d.getMinutes().toString().padStart(2,'0')}:${d.getSeconds().toString().padStart(2,'0')}`;
  };

  if (health?.status === 'ok')
    events.push({ time: ts(0), msg: 'All systems operational — health check passed', st: 'Success' });
  else if (health?.status === 'degraded')
    events.push({ time: ts(0), msg: 'System degraded — one or more services unavailable', st: 'Warning' });
  else
    events.push({ time: ts(0), msg: 'Backend unreachable — cannot connect to API', st: 'Error' });

  if (health?.workers === 'running')
    events.push({ time: ts(3), msg: `OCR worker pool active (queue depth: ${health?.queue_depth ?? 0} jobs)`, st: 'Success' });
  else
    events.push({ time: ts(3), msg: 'OCR worker pool is STOPPED — no jobs will be processed', st: 'Error' });

  if (health?.supabase === 'connected')
    events.push({ time: ts(6), msg: 'Supabase database connection verified', st: 'Success' });
  else
    events.push({ time: ts(6), msg: `Supabase unreachable: ${health?.supabase || 'unknown'}`, st: 'Error' });

  if (progress?.total > 0) {
    events.push({
      time: ts(12),
      msg: `OCR pipeline: ${progress.completed}/${progress.total} docs processed (${progress.percent_complete ?? 0}% complete)`,
      st: 'Info',
    });
    if (progress.failed > 0)
      events.push({ time: ts(20), msg: `${progress.failed} OCR job(s) failed — check logs for details`, st: 'Warning' });
    if (progress.processing > 0)
      events.push({ time: ts(25), msg: `${progress.processing} OCR job(s) currently running`, st: 'Info' });
  }

  return events.slice(0, 6);
}

/* ─── derive alerts from live data ── */
function buildAlerts(health, progress) {
  const alerts = [];

  if (!health) {
    alerts.push({
      level: 'Critical',
      title: 'Backend Offline',
      msg: 'Cannot reach the API server at http://127.0.0.1:8000. Ensure the backend is running.',
      color: '#DC2626', bg: '#FEE2E2', border: '#FECACA',
    });
    return alerts;
  }

  if (health.supabase !== 'connected')
    alerts.push({
      level: 'Critical',
      title: 'Database Unreachable',
      msg: `Supabase connection failed: ${health.supabase}. Check your SUPABASE_URL and SUPABASE_KEY env vars.`,
      color: '#DC2626', bg: '#FEE2E2', border: '#FECACA',
    });

  if (health.workers !== 'running')
    alerts.push({
      level: 'Critical',
      title: 'OCR Workers Stopped',
      msg: 'The background OCR worker pool is not running. No documents will be processed until it is restarted.',
      color: '#DC2626', bg: '#FEE2E2', border: '#FECACA',
    });

  if (!health.env_loaded)
    alerts.push({
      level: 'Warning',
      title: 'Missing Environment Variables',
      msg: 'SUPABASE_URL or SUPABASE_KEY is not set. Check your .env file.',
      color: '#D97706', bg: '#FEF3C7', border: '#FDE68A',
    });

  if ((health.queue_depth ?? 0) > 50)
    alerts.push({
      level: 'Warning',
      title: 'Queue Backlog',
      msg: `${health.queue_depth} jobs are waiting in the OCR queue. Workers may be slower than ingest rate.`,
      color: '#D97706', bg: '#FEF3C7', border: '#FDE68A',
    });

  if (progress?.failed > 5)
    alerts.push({
      level: 'Warning',
      title: 'High OCR Failure Rate',
      msg: `${progress.failed} documents have permanently failed OCR. Inspect server logs for errors.`,
      color: '#D97706', bg: '#FEF3C7', border: '#FDE68A',
    });

  return alerts;
}

/* ─── derive overall health score ── */
function calcScore(health, progress) {
  if (!health) return 0;
  let score = 0;
  if (health.supabase === 'connected') score += 35;
  if (health.workers  === 'running')   score += 35;
  if (health.env_loaded)               score += 20;
  if ((health.queue_depth ?? 0) < 20)  score += 10;

  // Deduct for OCR failures
  if (progress?.total > 0) {
    const failRate = (progress.failed ?? 0) / progress.total;
    score = Math.max(0, score - Math.round(failRate * 20));
  }
  return Math.min(score, 100);
}


export default function SystemHealth() {
  const [health,    setHealth]    = useState(null);
  const [progress,  setProgress]  = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [lastFetch, setLastFetch] = useState(null);
  const [error,     setError]     = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, p] = await Promise.allSettled([
        apiGetHealth(),
        apiGetProgress(),
      ]);
      setHealth(  h.status === 'fulfilled' ? h.value : null);
      setProgress(p.status === 'fulfilled' ? p.value : null);
      if (h.status === 'rejected') setError('Backend unreachable');
    } catch (e) {
      setError(e.message || 'Failed to fetch health data');
    } finally {
      setLoading(false);
      setLastFetch(new Date());
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 10_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const statusCards = buildStatusCards(health);
  const events      = buildEvents(health, progress);
  const alerts      = buildAlerts(health, progress);
  const score       = calcScore(health, progress);
  const isOnline    = health?.status === 'ok' || health?.status === 'degraded';

  /* ─── colour for score ring ── */
  const ringColor = score >= 80 ? '#16A34A' : score >= 50 ? '#D97706' : '#DC2626';
  const scoreLabel = score >= 80 ? 'Healthy' : score >= 50 ? 'Degraded' : 'Critical';

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
      <Navbar title="System Health" subtitle="Live status of OCR pipeline and backend services" />

      <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', gap: 24, boxSizing: 'border-box' }}>

        {/* ── Top bar: connection banner + refresh ── */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 16px', borderRadius: 10,
            background: isOnline ? '#F0FDF4' : '#FEF2F2',
            border: `1px solid ${isOnline ? '#86EFAC' : '#FECACA'}`,
          }}>
            {isOnline
              ? <Wifi size={16} color="#16A34A" />
              : <WifiOff size={16} color="#DC2626" />}
            <span style={{ fontSize: 13, fontWeight: 700, color: isOnline ? '#15803D' : '#DC2626' }}>
              {isOnline
                ? `System Online${health?.status === 'degraded' ? ' — Degraded' : ''}`
                : 'System Offline — backend unreachable'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            {lastFetch && (
              <span style={{ fontSize: 12, color: '#94A3B8', fontWeight: 500 }}>
                <Clock size={12} style={{ display:'inline', marginRight:4, verticalAlign:'middle' }} />
                Updated {lastFetch.toLocaleTimeString()}
              </span>
            )}
            <button
              onClick={fetchAll}
              disabled={loading}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '8px 14px', borderRadius: 8,
                background: '#F8FAFC', border: '1px solid #E2E8F0',
                fontSize: 13, fontWeight: 600, color: '#475569',
                cursor: loading ? 'not-allowed' : 'pointer',
                opacity: loading ? 0.6 : 1,
              }}
            >
              <RefreshCw size={13} style={{ animation: loading ? 'spin 0.8s linear infinite' : 'none' }} />
              Refresh
            </button>
          </div>
        </div>

        {/* ── 1. Status Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          {statusCards.map(s => (
            <div key={s.label} style={{
              background: '#FFFFFF', border: '1px solid #E5E7EB',
              borderRadius: 12, padding: 20,
              display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
              minHeight: 90,
              borderTop: `3px solid ${s.color}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 30, height: 30, borderRadius: 8, background: s.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <s.icon size={15} color={s.color} />
                </div>
                <span style={{ fontSize: 13, fontWeight: 700, color: '#334155' }}>{s.label}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12 }}>
                <StatusPulse color={s.color} />
                <span style={{ fontSize: 16, fontWeight: 800, color: '#0F172A' }}>{s.status}</span>
              </div>
            </div>
          ))}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 24 }}>

          {/* ── Left: Metrics + Events ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* 2. OCR Pipeline Metrics */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              {[
                {
                  label: 'Total Documents',
                  value: progress?.total       ?? '—',
                  unit:  'docs tracked',
                  color: '#2563EB',
                },
                {
                  label: 'Completed',
                  value: progress?.completed   ?? '—',
                  unit:  `${progress?.percent_complete ?? 0}% done`,
                  color: '#16A34A',
                },
                {
                  label: 'Pending / Processing',
                  value: ((progress?.pending ?? 0) + (progress?.processing ?? 0)),
                  unit:  'in queue',
                  color: '#D97706',
                },
                {
                  label: 'Failed Jobs',
                  value: progress?.failed      ?? '—',
                  unit:  'permanent failures',
                  color: progress?.failed > 0 ? '#DC2626' : '#64748B',
                },
              ].map(m => (
                <div key={m.label} style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, padding: 20 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>{m.label}</div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: m.color }}>
                    {m.value}
                    <span style={{ fontSize: 13, fontWeight: 600, color: '#64748B', marginLeft: 6 }}>{m.unit}</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Queue depth + worker info */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, padding: 20 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>In-Memory Queue Depth</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: (health?.queue_depth ?? 0) > 20 ? '#D97706' : '#0F172A' }}>
                  {health?.queue_depth ?? '—'}
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#64748B', marginLeft: 6 }}>jobs waiting</span>
                </div>
              </div>
              <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, padding: 20 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Worker Pool</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: health?.workers === 'running' ? '#16A34A' : '#DC2626' }}>
                  {health?.workers === 'running' ? 'Active' : 'Stopped'}
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#64748B', marginLeft: 6 }}>
                    {health?.workers === 'running' ? '10 workers' : 'no workers'}
                  </span>
                </div>
              </div>
            </div>

            {/* 3. Live Events */}
            <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, overflow: 'hidden', flex: 1, display: 'flex', flexDirection: 'column' }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid #F1F5F9', background: '#F8FAFC', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Activity size={16} color="#2563EB" />
                <span style={{ fontSize: 15, fontWeight: 700, color: '#0F172A' }}>Live System Events</span>
                {loading && <div style={{ marginLeft: 'auto', width: 12, height: 12, borderRadius: '50%', border: '2px solid #BFDBFE', borderTopColor: '#2563EB', animation: 'spin 0.8s linear infinite' }} />}
              </div>
              <div style={{ padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}>
                {events.length === 0 ? (
                  <div style={{ fontSize: 13, color: '#94A3B8', textAlign: 'center', padding: '20px 0' }}>No events — backend may be offline</div>
                ) : events.map((e, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
                    <div style={{ width: 70, fontSize: 11, fontWeight: 700, color: '#94A3B8', marginTop: 2, fontFamily: 'monospace', flexShrink: 0 }}>{e.time}</div>
                    <div style={{
                      width: 8, height: 8, borderRadius: '50%', marginTop: 5, flexShrink: 0,
                      background: e.st === 'Success' ? '#16A34A' : e.st === 'Error' ? '#DC2626' : e.st === 'Warning' ? '#D97706' : '#2563EB',
                    }} />
                    <div style={{ flex: 1, fontSize: 13, fontWeight: 500, color: '#0F172A', lineHeight: 1.4 }}>{e.msg}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* ── Right: Score + Alerts ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

            {/* 4. Health Score Donut */}
            <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, padding: 24, display: 'flex', flexDirection: 'column', alignItems: 'center', textAlign: 'center' }}>
              <div style={{ position: 'relative', width: 140, height: 140, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 16 }}>
                <svg viewBox="0 0 36 36" style={{ position: 'absolute', width: '100%', height: '100%', transform: 'rotate(-90deg)' }}>
                  <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                    fill="none" stroke="#F1F5F9" strokeWidth="3" />
                  <path d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                    fill="none" stroke={ringColor} strokeWidth="3"
                    strokeDasharray={`${score}, 100`}
                    style={{ transition: 'stroke-dasharray 1s ease-out' }}
                  />
                </svg>
                <div style={{ fontSize: 30, fontWeight: 800, color: ringColor }}>{score}%</div>
              </div>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0F172A' }}>System {scoreLabel}</div>
              <div style={{ fontSize: 12, color: '#64748B', marginTop: 4 }}>
                {isOnline ? `Backend responding · Supabase ${health?.supabase}` : 'Cannot reach backend server'}
              </div>
            </div>

            {/* 5. Alerts */}
            <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, overflow: 'hidden', flex: 1 }}>
              <div style={{ padding: '14px 20px', borderBottom: '1px solid #F1F5F9', background: '#F8FAFC', display: 'flex', alignItems: 'center', gap: 8 }}>
                <AlertTriangle size={16} color={alerts.length > 0 ? '#D97706' : '#16A34A'} />
                <span style={{ fontSize: 15, fontWeight: 700, color: '#0F172A' }}>
                  Active Alerts {alerts.length > 0 ? `(${alerts.length})` : ''}
                </span>
              </div>
              <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
                {alerts.length === 0 ? (
                  <div style={{ padding: 14, borderRadius: 10, background: '#F0FDF4', border: '1px solid #86EFAC', display: 'flex', alignItems: 'center', gap: 10 }}>
                    <CheckCircle2 size={18} color="#16A34A" />
                    <div style={{ fontSize: 13, fontWeight: 600, color: '#15803D' }}>All systems operational — no active alerts.</div>
                  </div>
                ) : alerts.map((a, i) => (
                  <div key={i} style={{ padding: 14, borderRadius: 10, background: a.bg, border: `1px solid ${a.border}` }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ padding: '2px 8px', borderRadius: 6, background: a.color, color: '#fff', fontSize: 10, fontWeight: 800, textTransform: 'uppercase' }}>{a.level}</span>
                      <span style={{ fontSize: 13, fontWeight: 700, color: '#0F172A' }}>{a.title}</span>
                    </div>
                    <div style={{ fontSize: 12, color: '#475569', lineHeight: 1.5 }}>{a.msg}</div>
                  </div>
                ))}
              </div>
            </div>

          </div>
        </div>
      </div>
    </div>
  );
}
