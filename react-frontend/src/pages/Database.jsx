import React, { useState, useEffect, useRef, useCallback } from 'react';
import axios from 'axios';
import Navbar from '../components/Navbar';
import UserDetailPanel from '../components/UserDetailPanel';
import { useData } from '../context/DataContext';
import { useApiStatus } from '../hooks/useApiStatus';
import { recordStatus, fmtDate } from '../utils/validation';
import { Search, RefreshCw, Zap, CheckCircle2, AlertCircle, XCircle, FileText, Database as DBIcon, X, Activity, Clock, ChevronRight } from 'lucide-react';

function StatusBadge({ user }) {
  if (user.ocr_status_combined === 'running')    return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#DBEAFE', color: '#2563EB' }}>Running</span>;
  if (user.ocr_status_combined === 'needs_ocr' || user.ocr_status_combined === 'not_started') return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#F1F5F9', color: '#64748B' }}>Pending</span>;
  const s = recordStatus(user);
  if (s === 'matched')          return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#DCFCE7', color: '#16A34A' }}>Verified</span>;
  if (s === 'system_extracted') return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#DBEAFE', color: '#2563EB' }}>Extracted</span>;
  if (s === 'needs_review')     return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#FEF3C7', color: '#D97706' }}>Review</span>;
  if (s === 'invalid')          return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#FEE2E2', color: '#DC2626' }}>Invalid</span>;
  return <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 12, fontWeight: 600, background: '#F1F5F9', color: '#64748B' }}>—</span>;
}

/* ── Document badge pill ──────────────────────────────────── */
const DOC_BADGE_MAP = {
  aadhaar:   { label: 'AD',  color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0' },
  pan:       { label: 'PAN', color: '#2563EB', bg: '#EFF6FF', border: '#BFDBFE' },
  tenth:     { label: '10',  color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  twelfth:   { label: '12',  color: '#7C3AED', bg: '#FAF5FF', border: '#E9D5FF' },
  degree:    { label: 'DEG', color: '#9333EA', bg: '#FAF5FF', border: '#E9D5FF' },
  diploma:   { label: 'DIP', color: '#EA580C', bg: '#FFF7ED', border: '#FED7AA' },
  semester:  { label: 'SEM', color: '#0284C7', bg: '#F0F9FF', border: '#BAE6FD' },
  semesters: { label: 'SEM', color: '#0284C7', bg: '#F0F9FF', border: '#BAE6FD' },
};

function DocBadges({ user }) {
  // PRIMARY source: user.doc_types from documents table (populated by backend list_users)
  // FALLBACK: user.aadhaar_number / user.pan_number from extracted_data (for old records)
  const typeSet = new Set(user.doc_types || []);

  // Fallback for aadhaar/pan if doc_types doesn't include them yet
  if ((user.aadhaar?.aadhaar_number || user.aadhaar_number) && !typeSet.has('aadhaar')) typeSet.add('aadhaar');
  if ((user.pan?.pan_number || user.pan_number) && !typeSet.has('pan')) typeSet.add('pan');

  // Canonical display order
  const ORDER = ['aadhaar', 'pan', 'tenth', 'twelfth', 'diploma', 'degree', 'semester'];
  const deduped = ORDER.filter(t => typeSet.has(t));

  if (deduped.length === 0) {
    return <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 500 }}>No records</span>;
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {deduped.map(type => {
        const cfg = DOC_BADGE_MAP[type];
        if (!cfg) return null;
        return (
          <span key={type} style={{
            fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 5,
            color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}`,
            whiteSpace: 'nowrap',
          }}>{cfg.label}</span>
        );
      })}
    </div>
  );
}

/* ── Academic docs badge ──────────────────────────────────── */
const ACADEMIC_BADGE_CONFIG = {
  tenth:    { label: '10th',    color: '#D97706', bg: '#FFFBEB', border: '#FDE68A' },
  twelfth:  { label: '12th',    color: '#7C3AED', bg: '#FAF5FF', border: '#E9D5FF' },
  diploma:  { label: 'Diploma', color: '#EA580C', bg: '#FFF7ED', border: '#FED7AA' },
  degree:   { label: 'Degree',  color: '#9333EA', bg: '#FAF5FF', border: '#E9D5FF' },
  semester: { label: 'Sem',     color: '#0284C7', bg: '#F0F9FF', border: '#BAE6FD' },
};

function AcademicsBadge({ user }) {
  const ACADEMIC_ORDER = ['tenth', 'twelfth', 'diploma', 'degree', 'semester'];
  const docTypes = new Set(user.doc_types || []);
  const acadTypes = ACADEMIC_ORDER.filter(t => docTypes.has(t));

  if (acadTypes.length === 0) {
    return <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 500 }}>No Academic Docs</span>;
  }
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {acadTypes.map(type => {
        const cfg = ACADEMIC_BADGE_CONFIG[type];
        if (!cfg) return null;
        return (
          <span key={type} style={{
            fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
            color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}`,
            whiteSpace: 'nowrap',
          }}>{cfg.label}</span>
        );
      })}
    </div>
  );
}

/* ── KYC-only doc badge (Aadhaar + PAN) ────────────────────── */
function KYCBadges({ user }) {
  const KYC_ORDER = ['aadhaar', 'pan'];
  const typeSet = new Set(user.doc_types || []);
  if ((user.aadhaar?.aadhaar_number || user.aadhaar_number) && !typeSet.has('aadhaar')) typeSet.add('aadhaar');
  if ((user.pan?.pan_number || user.pan_number) && !typeSet.has('pan')) typeSet.add('pan');
  const present = KYC_ORDER.filter(t => typeSet.has(t));
  if (present.length === 0) return <span style={{ fontSize: 11, color: '#CBD5E1', fontWeight: 500 }}>—</span>;
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
      {present.map(type => {
        const cfg = DOC_BADGE_MAP[type];
        if (!cfg) return null;
        return (
          <span key={type} style={{
            fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 5,
            color: cfg.color, background: cfg.bg, border: `1px solid ${cfg.border}`,
          }}>{cfg.label}</span>
        );
      })}
    </div>
  );
}

function ConfCell({ user }) {
  const raw = user.confidence;
  const pct = raw == null ? 0 : Math.round(raw);

  let color;
  if (pct >= 90)      color = '#10B981';
  else if (pct >= 70) color = '#F59E0B';
  else if (pct >= 50) color = '#F97316';
  else                color = '#EF4444';

  return (
    <span style={{ fontSize: 13, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
      {pct}%
    </span>
  );
}


function parseQuery(q) {
  const s = (q || '').toLowerCase().trim();
  if (!s) return { explanation: null, filterFn: () => true };
  const isMismatch  = /mismatch|review|different|conflict/.test(s);
  const isVerified  = /verified|matched|clean|approved/.test(s);
  const isExtracted = /extract|auto|no original/.test(s);
  const isInvalid   = /invalid|failed|error/.test(s);
  let explanation = null;
  if (isMismatch)  explanation = 'Needs review';
  if (isVerified)  explanation = 'Verified only';
  if (isExtracted) explanation = 'Auto-extracted';
  if (isInvalid)   explanation = 'Invalid only';
  const filterFn = (u) => {
    const st = recordStatus(u);
    if (isMismatch)  return st === 'needs_review';
    if (isVerified)  return st === 'matched';
    if (isExtracted) return st === 'system_extracted';
    if (isInvalid)   return st === 'invalid';
    return String(u.name || '').toLowerCase().includes(s)
      || String(u.final_name || '').toLowerCase().includes(s)
      || String(u.original_name || '').toLowerCase().includes(s)
      || String(u.final_aadhaar || '').includes(s)
      || String(u.aadhaar_number || '').includes(s)
      || String(u.final_pan || '').toLowerCase().includes(s)
      || String(u.pan_number || '').toLowerCase().includes(s)
      || String(u.id || '').includes(s);
  };
  return { explanation, filterFn };
}

function SkeletonRow() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', height: 52, padding: '0 16px', borderBottom: '1px solid #F1F5F9' }}>
      <div style={{ width: 60 }}> <div className="skeleton" style={{ height: 12, width: 30, borderRadius: 6 }} /> </div>
      <div style={{ width: 180 }}> <div className="skeleton" style={{ height: 12, width: 120, borderRadius: 6 }} /> </div>
      <div style={{ width: 160 }}> <div className="skeleton" style={{ height: 12, width: 100, borderRadius: 6 }} /> </div>
      <div style={{ width: 140 }}> <div className="skeleton" style={{ height: 12, width: 90, borderRadius: 6 }} /> </div>
      <div style={{ width: 110 }}> <div className="skeleton" style={{ height: 24, width: 50, borderRadius: 12 }} /> </div>
      <div style={{ width: 160 }}> <div className="skeleton" style={{ height: 24, width: 100, borderRadius: 12 }} /> </div>
      <div style={{ width: 80 }}> <div className="skeleton" style={{ height: 12, width: 30, borderRadius: 6 }} /> </div>
      <div style={{ width: 140 }}> <div className="skeleton" style={{ height: 24, width: 70, borderRadius: 12 }} /> </div>
      <div style={{ width: 120 }}> <div className="skeleton" style={{ height: 12, width: 40, borderRadius: 6 }} /> </div>
      <div style={{ width: 140 }}> <div className="skeleton" style={{ height: 12, width: 80, borderRadius: 6 }} /> </div>
    </div>
  );
}

const FILTERS = [
  { key: 'ALL',              label: 'All Records',  color: '#2563EB', bg: '#DBEAFE' },
  { key: 'matched',          label: 'Verified',     color: '#16A34A', bg: '#DCFCE7' },
  { key: 'system_extracted', label: 'Extracted',    color: '#7C3AED', bg: '#EDE9FE' },
  { key: 'needs_review',     label: 'Review',       color: '#D97706', bg: '#FEF3C7' },
  { key: 'invalid',          label: 'Invalid',      color: '#DC2626', bg: '#FEE2E2' },
];

export default function Database() {
  const { users, setUsers, loading, error, loadData: load, refreshUser } = useData();
  const { status: apiStatus } = useApiStatus();
  const [isOffline, setIsOffline] = useState(!navigator.onLine || apiStatus === 'offline');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatus] = useState('ALL');
  const [selectedUser, setSelectedUser] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [bulkOcr, setBulkOcr] = useState({
    running: false,
    done: false,
    total: 0,
    processed: 0,
    success: 0,
    failed: 0,
    skipped: 0,
    percent: 0,
    elapsed: 0,
    errors: [],
    msg: null,
    recordsPerMin: 0,
  });
  const [sFocused, setSFocused] = useState(false);
  const pollRef = useRef(null);
  const startTimeRef = useRef(null);
  // Tracks which user IDs we've already fetched fresh data for during this OCR run
  const seenRefreshedRef = useRef(new Set());
  // Grace timer: we wait 45s of sustained offline before stopping OCR.
  // A single transient health check timeout must never kill the batch.
  const offlineGraceTimerRef = useRef(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    if (offlineGraceTimerRef.current) { clearTimeout(offlineGraceTimerRef.current); offlineGraceTimerRef.current = null; }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  useEffect(() => {
    const handleOnline = () => setIsOffline(apiStatus === 'offline');
    const handleOffline = () => setIsOffline(true);
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    setIsOffline(!navigator.onLine || apiStatus === 'offline');
    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, [apiStatus]);

  useEffect(() => {
    if (isOffline && bulkOcr.running) {
      // Start a grace period timer: only stop OCR if offline is sustained for 45s.
      // A single transient health check timeout (e.g. during heavy OCR load)
      // must NOT immediately kill the batch. useApiStatus already requires
      // 3 consecutive failures before setting offline (~45s), so by the time
      // we get here, the connection is genuinely down.
      if (!offlineGraceTimerRef.current) {
        console.warn('[Database] Backend offline detected — waiting 45s before stopping OCR batch');
        offlineGraceTimerRef.current = setTimeout(() => {
          offlineGraceTimerRef.current = null;
          // Re-check: if we're still offline AND still running, then stop
          setBulkOcr(prev => {
            if (prev.running) {
              stopPoll();
              return {
                ...prev,
                running: false,
                done: true,
                isNetworkError: true,
                isError: true,
                msg: 'The system went offline during OCR processing. Progress has been saved safely.',
              };
            }
            return prev;
          });
        }, 45000);
      }
    } else if (!isOffline && offlineGraceTimerRef.current) {
      // Connection restored before grace period expired — cancel the timer
      console.log('[Database] Backend back online — cancelling offline grace timer');
      clearTimeout(offlineGraceTimerRef.current);
      offlineGraceTimerRef.current = null;
    }
  }, [isOffline, bulkOcr.running, stopPoll]);

  const handleBulkOcr = async () => {
    if (bulkOcr.running) return;
    stopPoll();
    startTimeRef.current = Date.now();
    // Reset the seen-refreshed set for this new OCR run
    seenRefreshedRef.current = new Set();

    setBulkOcr(p => ({ ...p, running: true, done: false, isError: false, msg: 'Starting bulk OCR…', percent: 0, processed: 0, total: 0, success: 0, failed: 0, skipped: 0, errors: [], recordsPerMin: 0 }));

    try {
      const res = await axios.post('/api/ocr/bulk');
      const d = res.data;

      if (d.already_running) {
        // Someone else triggered it — just start polling status
      } else if (d.jobs_queued === 0) {
        setBulkOcr({ running: false, done: true, msg: '✓ All records already processed — nothing to do.', percent: 100, processed: 0, total: 0, success: 0, failed: 0, skipped: 0, errors: [], recordsPerMin: 0 });
        setTimeout(() => setBulkOcr(p => ({ ...p, done: false, msg: null })), 5000);
        return;
      } else {
        setBulkOcr(p => ({ ...p, total: d.jobs_queued, msg: `Processing ${d.jobs_queued} records…` }));
      }

      // Poll /api/ocr/bulk/status every 1.5s
      pollRef.current = setInterval(async () => {
        try {
          const pr = await axios.get('/api/ocr/bulk/status');
          const s = pr.data;
          const pct   = s.percent_complete ?? 0;
          const done  = !s.running && s.started_at;

          // ── Targeted per-row refresh for newly completed users ──────────────
          // The backend tracks recently_completed user_ids since the last poll.
          // We fetch fresh data for each one immediately, updating only those
          // rows in the table — no expensive full reload needed.
          const recentlyDone = s.recently_completed || [];
          const toRefresh = recentlyDone.filter(uid => !seenRefreshedRef.current.has(uid));
          if (toRefresh.length > 0) {
            toRefresh.forEach(uid => seenRefreshedRef.current.add(uid));
            // Fire refreshes in parallel — each is a small single-user query
            Promise.all(toRefresh.map(uid => refreshUser(uid))).catch(() => {});
          }

          // ── Records per minute metric ───────────────────────────────────────
          const elapsedMin = (s.elapsed_sec || 0) / 60;
          const rpm = elapsedMin > 0.05 ? Math.round((s.processed || 0) / elapsedMin) : 0;

          setBulkOcr({
            running:   s.running,
            done:      !!done,
            total:     s.total     ?? 0,
            processed: s.processed ?? 0,
            success:   s.success   ?? 0,
            failed:    s.failed    ?? 0,
            skipped:   s.skipped   ?? 0,
            percent:   pct,
            elapsed:   s.elapsed_sec ?? 0,
            errors:    s.errors    ?? [],
            recordsPerMin: rpm,
            msg: s.running
              ? `Processing…  ${s.processed ?? 0} / ${s.total ?? 0} records  (${pct}%)`
              : s.failed > 0
                ? `⚠ OCR complete — ${s.failed} failed, ${s.success} succeeded`
                : `✓ OCR complete — ${s.success} processed, ${s.skipped} skipped`,
          });

          if (!s.running && s.started_at) {
            stopPoll();
            // One final full refresh to guarantee nothing was missed
            setTimeout(() => load(true), 800);
            setTimeout(() => setBulkOcr(p => ({ ...p, done: false, msg: null })), 8000);
          }
        } catch (_) { /* network blip — keep polling */ }
      }, 4000);

    } catch (e) {
      stopPoll();
      setBulkOcr({ running: false, done: false, isError: true, msg: `Error: ${e?.response?.data?.detail || e.message || 'OCR failed to start'}`, percent: 0, processed: 0, total: 0, success: 0, failed: 0, skipped: 0, errors: [], recordsPerMin: 0 });
      setTimeout(() => setBulkOcr(p => ({ ...p, msg: null })), 6000);
    }
  };

  const handleStopOcr = async () => {
    try {
      stopPoll();
      setBulkOcr(p => ({
        ...p,
        running: false,
        done: true,
        msg: `⚠ OCR Stopped Manually — ${p.processed} records processed.`,
      }));
      await axios.post('/api/ocr/bulk/stop');
      setTimeout(() => load(true), 500); // refresh table
      setTimeout(() => setBulkOcr(p => ({ ...p, done: false, msg: null })), 5000); // reset button to 'Run OCR'
    } catch (e) {
      console.error("Failed to stop OCR:", e);
    }
  };
  const handleRowClick = u => { setSelectedUser(u); setIsDrawerOpen(true); };



  const { explanation, filterFn } = parseQuery(search);

  const counts = { ALL: users.length, matched: 0, system_extracted: 0, needs_review: 0, invalid: 0 };
  users.forEach(u => { const s = recordStatus(u); counts[s] = (counts[s] || 0) + 1; });

  const filtered = users.filter(u => {
    if (u._softRetain) return true;
    if (statusFilter !== 'ALL' && recordStatus(u) !== statusFilter) return false;
    return filterFn(u);
  });
  const selIdx = filtered.findIndex(u => u.id === selectedUser?.id);
  const hasNext = selIdx >= 0 && selIdx < filtered.length - 1;
  const hasPrev = selIdx > 0;

  const filterCards = FILTERS.map(f => ({ ...f, count: counts[f.key] || 0 }));

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden', minHeight: 0 }}>
      {/* Header outside main padding for top border matching */}
      <Navbar title="Database" subtitle="View and manage all processed records" />

      <div style={{ padding: 24, maxWidth: 1200, margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>

        {/* 2. KPI Cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 16 }}>
          {filterCards.map(f => {
            const active = statusFilter === f.key;
            return (
              <div
                key={f.key}
                onClick={() => setStatus(f.key)}
                style={{
                  height: 90, padding: 16, borderRadius: 12,
                  background: active ? f.bg : '#FFFFFF',
                  border: `1px solid ${active ? f.color : '#E5E7EB'}`,
                  cursor: 'pointer', transition: 'all 150ms ease',
                  display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 6,
                  boxShadow: active ? `0 0 0 1px ${f.color}` : 'none',
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 700, color: active ? f.color : '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{f.label}</div>
                <div style={{ fontSize: 24, fontWeight: 800, color: active ? f.color : '#0F172A', lineHeight: 1 }}>{f.count}</div>
              </div>
            );
          })}
        </div>

        {/* 3. Search + Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginTop: 24 }}>

          {/* Search bar */}
          <div style={{
            position: 'relative', flex: 1, minWidth: 0,
            background: '#FFFFFF', border: '1px solid #E5E7EB',
            borderRadius: 10, boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
            transition: 'box-shadow 150ms ease',
            overflow: 'hidden',
          }}>
            <Search size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: sFocused ? '#2563EB' : '#94A3B8', transition: 'color 150ms', pointerEvents: 'none' }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onFocus={() => setSFocused(true)}
              onBlur={() => setSFocused(false)}
              placeholder="Search by name, ID, or type a status filter..."
              style={{
                width: '100%', height: 42, padding: '0 38px 0 40px',
                boxSizing: 'border-box',
                borderRadius: 10, border: `1.5px solid ${sFocused ? '#2563EB' : 'transparent'}`,
                fontSize: 14, color: '#0F172A', outline: 'none', transition: 'all 150ms ease',
                background: 'transparent',
                boxShadow: sFocused ? '0 0 0 3px rgba(37,99,235,0.08)' : 'none',
              }}
            />
            {explanation && <span style={{ position: 'absolute', right: search ? 36 : 12, top: '50%', transform: 'translateY(-50%)', fontSize: 11, fontWeight: 700, color: '#2563EB', background: '#DBEAFE', padding: '2px 8px', borderRadius: 5, pointerEvents: 'none' }}>{explanation}</span>}
            {search && <button onClick={() => setSearch('')} style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#94A3B8', display: 'flex', padding: 4 }}><X size={14} /></button>}
          </div>

          {/* Action buttons — fixed width, never shrink */}
          <div style={{ display: 'flex', gap: 8, flexShrink: 0, alignItems: 'center' }}>
            <button
              onClick={load}
              disabled={loading}
              style={{
                height: 42, padding: '0 18px', borderRadius: 10,
                background: '#FFFFFF', border: '1px solid #E5E7EB',
                display: 'flex', alignItems: 'center', gap: 7,
                fontSize: 13, fontWeight: 600, color: '#334155',
                cursor: loading ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap', transition: 'all 150ms ease',
                boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
              }}
              onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = '#F8FAFC'; e.currentTarget.style.borderColor = '#CBD5E1'; }}}
              onMouseLeave={e => { e.currentTarget.style.background = '#FFFFFF'; e.currentTarget.style.borderColor = '#E5E7EB'; }}
            >
              <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              Refresh
            </button>
            <button
              onClick={handleBulkOcr}
              disabled={bulkOcr.running || isOffline}
              style={{
                height: 42, padding: '0 18px', borderRadius: 10,
                background: isOffline ? '#94A3B8' : bulkOcr.done && !bulkOcr.isNetworkError ? '#16A34A' : '#2563EB', border: 'none',
                display: 'flex', alignItems: 'center', gap: 7,
                fontSize: 13, fontWeight: 600, color: '#FFFFFF',
                cursor: bulkOcr.running || isOffline ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap', transition: 'all 150ms ease',
                opacity: (bulkOcr.running || isOffline) ? 0.85 : 1,
                boxShadow: isOffline ? 'none' : '0 1px 3px rgba(37,99,235,0.3)',
              }}
              onMouseEnter={e => { if (!bulkOcr.running && !isOffline) e.currentTarget.style.opacity = '0.9'; }}
              onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}
            >
              {isOffline ? <AlertCircle size={14} /> : bulkOcr.running
                ? <RefreshCw size={14} style={{ animation: 'spin 1s linear infinite' }} />
                : bulkOcr.done && !bulkOcr.isNetworkError
                  ? <CheckCircle2 size={14} />
                  : <Zap size={14} />}
              {isOffline ? 'Waiting For Connection' : bulkOcr.running ? 'Processing OCR…' : bulkOcr.done && !bulkOcr.isNetworkError ? 'OCR Done' : (bulkOcr.isNetworkError && !isOffline) ? 'Resume OCR' : 'Run OCR'}
            </button>
          </div>
        </div>


        {/* Error State */}
        {error && (
          <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, padding: '16px 20px', marginTop: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: '#FEF3C7', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><AlertCircle size={18} color="#D97706" /></div>
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A' }}>Unable to load records</div>
                <div style={{ fontSize: 13, color: '#64748B', marginTop: 2 }}>{error}</div>
              </div>
            </div>
            <button onClick={load} style={{ height: 36, padding: '0 16px', borderRadius: 8, background: '#F1F5F9', border: 'none', fontSize: 13, fontWeight: 600, color: '#334155', cursor: 'pointer' }}>Retry</button>
          </div>
        )}

        {/* OCR Progress Banner */}
        {(bulkOcr.running || bulkOcr.msg) && (
          <div style={{
            marginTop: 16, borderRadius: 12, overflow: 'hidden',
            border: `1px solid ${bulkOcr.isError || bulkOcr.failed > 0 ? '#FECACA' : bulkOcr.running ? '#BFDBFE' : '#BBF7D0'}`,
            background: bulkOcr.isError || bulkOcr.failed > 0 ? '#FEF2F2' : bulkOcr.running ? '#EFF6FF' : '#F0FDF4',
          }}>
            {/* Top bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px' }}>
              <div style={{
                width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                background: bulkOcr.isError || bulkOcr.failed > 0 ? '#FEE2E2' : bulkOcr.running ? '#DBEAFE' : '#DCFCE7',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
              }}>
                {bulkOcr.running
                  ? <Activity size={16} color="#2563EB" />
                  : (bulkOcr.isError || bulkOcr.failed > 0)
                    ? <AlertCircle size={16} color="#DC2626" />
                    : <CheckCircle2 size={16} color="#16A34A" />}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#0F172A' }}>
                  {bulkOcr.isNetworkError ? 'OCR Interrupted — Connection Lost' : bulkOcr.running ? 'Bulk OCR Processing…' : bulkOcr.isError ? 'OCR Failed' : bulkOcr.failed > 0 ? 'OCR Completed with Errors' : 'OCR Completed'}
                </div>
                <div style={{ fontSize: 12, color: '#475569', marginTop: 2 }}>
                  {bulkOcr.isNetworkError 
                    ? (isOffline ? "The system went offline during OCR processing. Progress has been saved safely." : "Connection Restored. You can resume OCR processing.")
                    : bulkOcr.msg}
                </div>
              </div>
              {(bulkOcr.running || bulkOcr.done) && bulkOcr.total > 0 && (
                <div style={{ display: 'flex', gap: 16, flexShrink: 0 }}>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#2563EB', lineHeight: 1 }}>{bulkOcr.processed}</div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Done</div>
                  </div>
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 18, fontWeight: 800, color: '#64748B', lineHeight: 1 }}>{bulkOcr.total}</div>
                    <div style={{ fontSize: 10, fontWeight: 600, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total</div>
                  </div>
                  {bulkOcr.skipped > 0 && (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#9333EA', lineHeight: 1 }}>{bulkOcr.skipped}</div>
                      <div style={{ fontSize: 10, fontWeight: 600, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Skipped</div>
                    </div>
                  )}
                  {bulkOcr.recordsPerMin > 0 && (
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 18, fontWeight: 800, color: '#059669', lineHeight: 1 }}>{bulkOcr.recordsPerMin}</div>
                      <div style={{ fontSize: 10, fontWeight: 600, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>rec/min</div>
                    </div>
                  )}
                  {bulkOcr.elapsed > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#64748B', fontSize: 12 }}>
                      <Clock size={12} />{bulkOcr.elapsed}s
                    </div>
                  )}
                  {bulkOcr.running && (
                    <button
                      onClick={handleStopOcr}
                      style={{
                        height: 28, padding: '0 10px', borderRadius: 6,
                        background: '#FFFFFF', border: '1px solid #FECACA',
                        display: 'flex', alignItems: 'center', gap: 6,
                        fontSize: 11, fontWeight: 700, color: '#DC2626',
                        cursor: 'pointer', transition: 'all 150ms ease',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = '#FEF2F2'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = '#FFFFFF'; }}
                    >
                      <XCircle size={14} />
                      Stop OCR
                    </button>
                  )}
                  {bulkOcr.isNetworkError && !isOffline && (
                    <button
                      onClick={handleBulkOcr}
                      style={{
                        height: 28, padding: '0 14px', borderRadius: 6,
                        background: '#2563EB', border: 'none',
                        display: 'flex', alignItems: 'center', gap: 6,
                        fontSize: 12, fontWeight: 700, color: '#FFFFFF',
                        cursor: 'pointer', transition: 'all 150ms ease',
                        boxShadow: '0 1px 2px rgba(37,99,235,0.3)'
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = '#1D4ED8'; }}
                      onMouseLeave={e => { e.currentTarget.style.background = '#2563EB'; }}
                    >
                      <RefreshCw size={14} />
                      Resume OCR
                    </button>
                  )}
                </div>
              )}
            </div>
            {/* Progress bar */}
            {bulkOcr.running && (
              <div style={{ height: 4, background: 'rgba(0,0,0,0.06)' }}>
                <div style={{
                  height: '100%',
                  width: `${bulkOcr.percent || 0}%`,
                  background: 'linear-gradient(90deg, #2563EB, #7C3AED)',
                  transition: 'width 0.6s ease',
                  borderRadius: '0 2px 2px 0',
                }} />
              </div>
            )}
          </div>
        )}

        {/* 4. Filter Bar */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 16 }}>
          {FILTERS.map(f => {
            const active = statusFilter === f.key;
            return (
              <button
                key={f.key}
                onClick={() => setStatus(f.key)}
                style={{
                  height: 32, padding: '0 16px', borderRadius: 999,
                  background: active ? '#F1F5F9' : '#FFFFFF',
                  border: `1px solid ${active ? '#CBD5E1' : '#E5E7EB'}`,
                  color: active ? '#0F172A' : '#64748B',
                  fontSize: 13, fontWeight: 600, cursor: 'pointer', transition: 'all 150ms ease',
                }}
              >
                {f.label}
              </button>
            );
          })}
        </div>

        {/* 5. Table Container */}
        <div style={{ marginTop: 16, background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 14, overflow: 'hidden', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          
          {/* Header Row */}
          <div style={{ display: 'flex', alignItems: 'center', height: 48, background: '#F8FAFC', padding: '0 16px', borderBottom: '1px solid #E5E7EB', fontSize: 13, fontWeight: 600, color: '#334155' }}>
            <div style={{ width: 52 }}>ID</div>
            <div style={{ width: 180 }}>Name</div>
            <div style={{ width: 150 }}>Aadhaar</div>
            <div style={{ width: 130 }}>PAN</div>
            <div style={{ width: 110 }}>Documents</div>
            <div style={{ width: 160 }}>Academics</div>
            <div style={{ width: 60 }}>Age</div>
            <div style={{ width: 130 }}>Status</div>
            <div style={{ width: 110 }}>Confidence</div>
            <div style={{ width: 130 }}>Date</div>
          </div>

          {/* Table Body */}
          <div style={{ flex: 1, overflowY: 'scroll' }}>
            {loading ? (
              [...Array(10)].map((_, i) => <SkeletonRow key={i} />)
            ) : filtered.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 240, color: '#94A3B8' }}>
                <DBIcon size={32} color="#CBD5E1" strokeWidth={1.5} style={{ marginBottom: 12 }} />
                <div style={{ fontSize: 15, fontWeight: 600, color: '#0F172A' }}>No records found</div>
                <div style={{ fontSize: 13, marginTop: 4 }}>Try adjusting your search or filters</div>
              </div>
            ) : (
              filtered.map(u => (
                <div
                  key={u.id}
                  onClick={() => handleRowClick(u)}
                  style={{
                    display: 'flex', alignItems: 'center', height: 52, padding: '0 16px',
                    borderBottom: '1px solid #F1F5F9', cursor: 'pointer',
                    transition: 'background 150ms ease',
                    background: selectedUser?.id === u.id ? '#F1F5F9' : 'transparent',
                  }}
                  onMouseEnter={e => { if (selectedUser?.id !== u.id) e.currentTarget.style.background = '#F8FAFC'; }}
                  onMouseLeave={e => { if (selectedUser?.id !== u.id) e.currentTarget.style.background = 'transparent'; }}
                >
                  <div style={{ width: 52, fontSize: 13, fontWeight: 600, color: '#64748B' }}>#{u.id}</div>
                  <div style={{ width: 180, fontSize: 14, fontWeight: 600, color: '#0F172A', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', paddingRight: 12 }} title={u.final_name || u.name || u.original_name}>
                    {u.final_name || u.name || u.original_name || '—'}
                  </div>
                  <div style={{ width: 150, fontSize: 12, color: '#475569', fontFamily: 'monospace' }}>{u.final_aadhaar || u.aadhaar_number || '—'}</div>
                  <div style={{ width: 130, fontSize: 12, color: '#475569', fontFamily: 'monospace' }}>{u.final_pan || u.pan_number || '—'}</div>
                  <div style={{ width: 110 }}><KYCBadges user={u} /></div>
                  <div style={{ width: 160 }}><AcademicsBadge user={u} /></div>
                  <div style={{ width: 60, fontSize: 13, fontWeight: 500, color: '#64748B' }}>{u.age ?? '—'}</div>
                  <div style={{ width: 130, display: 'flex' }}><StatusBadge user={u} /></div>
                  <div style={{ width: 110, paddingRight: 4 }}><ConfCell user={u} /></div>
                  <div style={{ width: 130, fontSize: 13, color: '#94A3B8' }}>{fmtDate(u.created_at)}</div>
                </div>
              ))
            )}
          </div>
          
        </div>
      </div>

      {/* Detail Panel */}
      <UserDetailPanel
        user={selectedUser} isOpen={isDrawerOpen} onClose={() => setIsDrawerOpen(false)}
        onActionSuccess={(u) => { 
          if (u) {
            // Update the row in the table with the fresh DB values
            setUsers(p => [...p.map(r => r.id === u.id ? u : r)].sort((a, b) => a.id - b.id));
            // Stay on the record so the user can see the verified state
            setSelectedUser(u);
          }
        }}
        onNext={() => { if (hasNext) setSelectedUser(filtered[selIdx + 1]); }}
        onPrev={() => { if (hasPrev) setSelectedUser(filtered[selIdx - 1]); }}
        hasNext={hasNext} hasPrev={hasPrev}
      />
    </div>
  );
}
