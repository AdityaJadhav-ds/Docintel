import React, { useEffect, useRef, useState } from 'react';
import { fetchAuditLogs } from '../api/api';
import Navbar from '../components/Navbar';
import { RefreshCw, Search, Download, Filter, FileText, CheckCircle2, XCircle, AlertCircle, X, ChevronRight, ChevronDown, Activity } from 'lucide-react';

const ACTION_MAP = {
  // Core actions (from synthesized events)
  'upload':                  { label: 'Upload',   color: '#2563EB', bg: '#DBEAFE' },
  'approve':                 { label: 'Approve',  color: '#16A34A', bg: '#DCFCE7' },
  'reject':                  { label: 'Reject',   color: '#DC2626', bg: '#FEE2E2' },
  'ocr_process':             { label: 'OCR',      color: '#9333EA', bg: '#F3E8FF' },
  'SUBMITTED_FOR_REVIEW':    { label: 'Register', color: '#0284C7', bg: '#E0F2FE' },
  // Review system actions
  'CREATED':                 { label: 'Created',  color: '#64748B', bg: '#F1F5F9' },
  'AUTO_APPROVED':           { label: 'Approve',  color: '#16A34A', bg: '#DCFCE7' },
  'AUTO_REJECTED':           { label: 'Reject',   color: '#DC2626', bg: '#FEE2E2' },
  'VERIFIED':                { label: 'Verified',  color: '#16A34A', bg: '#DCFCE7' },
  'APPROVED':                { label: 'Approve',  color: '#16A34A', bg: '#DCFCE7' },
  'REJECTED':                { label: 'Reject',   color: '#DC2626', bg: '#FEE2E2' },
  'CORRECTED':               { label: 'Edit',     color: '#2563EB', bg: '#DBEAFE' },
  'REPROCESS_REQUESTED':     { label: 'OCR',      color: '#9333EA', bg: '#F3E8FF' },
  'REPROCESSING':            { label: 'OCR',      color: '#9333EA', bg: '#F3E8FF' },
  'STATUS_CHANGED':          { label: 'Edit',     color: '#2563EB', bg: '#DBEAFE' },
  // Legacy
  'LOGIN':                   { label: 'Login',    color: '#6366F1', bg: '#E0E7FF' },
  'FINAL_DECISION':          { label: 'Approve',  color: '#16A34A', bg: '#DCFCE7' },
  'edit':                    { label: 'Edit',     color: '#2563EB', bg: '#DBEAFE' },
  'error':                   { label: 'Error',    color: '#DC2626', bg: '#FEE2E2' },
  'PROCESS_START':           { label: 'OCR',      color: '#9333EA', bg: '#F3E8FF' },
  'STATE_CHANGE':            { label: 'Edit',     color: '#2563EB', bg: '#DBEAFE' },
};

function fmtTs(s) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return s; }
}

/* ── Detail Drawer ─────────────────────────────────────── */
function DetailDrawer({ log, isOpen, onClose }) {
  if (!isOpen || !log) return null;
  const conf = ACTION_MAP[log.action] || { label: log.action || 'Event', color: '#64748B', bg: '#F1F5F9' };

  return (
    <>
      <div style={{ position: 'fixed', inset: 0, background: 'rgba(15,23,42,0.35)', backdropFilter: 'blur(3px)', zIndex: 1000 }} onClick={onClose} />
      <div style={{
        position: 'fixed', top: 0, right: 0, width: 460, height: '100vh',
        background: '#FFFFFF', boxShadow: '-12px 0 40px rgba(15,23,42,0.12)', zIndex: 1001,
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px', borderBottom: '1px solid #E5E7EB', display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: conf.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
            <Activity size={18} color={conf.color} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#0F172A' }}>Log Details</div>
            <div style={{ fontSize: 12, color: '#94A3B8', marginTop: 1 }}>{fmtTs(log.created_at || log.timestamp)}</div>
          </div>
          <button onClick={onClose} style={{ background: '#F8FAFC', border: '1px solid #E5E7EB', borderRadius: 8, cursor: 'pointer', padding: 8, color: '#64748B', display: 'flex' }}>
            <X size={16} />
          </button>
        </div>

        <div style={{ padding: '24px', flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Meta grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {[
              { label: 'User / Actor', value: log.user_id || log.actor_id || 'System' },
              { label: 'Action',       value: conf.label },
              { label: 'Entity ID',    value: log.entity_id || '—' },
              { label: 'Status',       value: log.action !== 'ERROR' ? 'Success' : 'Failed' },
            ].map(f => (
              <div key={f.label} style={{ background: '#F8FAFC', border: '1px solid #E5E7EB', borderRadius: 10, padding: '12px 14px' }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{f.label}</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A' }}>{f.value}</div>
              </div>
            ))}
          </div>

          {/* State changes */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>State Changes</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div style={{ background: '#F8FAFC', border: '1px solid #E5E7EB', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#94A3B8', marginBottom: 6, textTransform: 'uppercase' }}>Previous State</div>
                <div style={{ fontSize: 13, color: '#475569', fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{log.previous_state || '—'}</div>
              </div>
              <div style={{ background: '#F0FDF4', border: '1px solid #86EFAC', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#16A34A', marginBottom: 6, textTransform: 'uppercase' }}>New State</div>
                <div style={{ fontSize: 13, color: '#14532D', fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{log.new_state || '—'}</div>
              </div>
            </div>
          </div>

          {/* Raw metadata */}
          {(log.details || log.metadata) && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Raw Details</div>
              <div style={{ background: '#0F172A', borderRadius: 10, padding: 16, overflowX: 'auto' }}>
                <pre style={{ margin: 0, fontSize: 12, color: '#94A3B8', fontFamily: 'monospace' }}>
                  {typeof (log.details || log.metadata) === 'object'
                    ? JSON.stringify(log.details || log.metadata, null, 2)
                    : (log.details || log.metadata)}
                </pre>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

/* ── Summary Card ──────────────────────────────────────── */
function SummaryCard({ label, val, color, bg, icon: Icon, accentColor }) {
  return (
    <div style={{
      background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 14,
      padding: '18px 20px', display: 'flex', alignItems: 'center', gap: 14,
      boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
      borderTop: `3px solid ${accentColor || color}`,
    }}>
      <div style={{ width: 44, height: 44, borderRadius: 12, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
        <Icon size={22} color={color} />
      </div>
      <div>
        <div style={{ fontSize: 26, fontWeight: 800, color: '#0F172A', lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>{val}</div>
        <div style={{ fontSize: 11, fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 4 }}>{label}</div>
      </div>
    </div>
  );
}

/* ── CSV Export helper ─────────────────────────────────── */
function exportCSV(logs) {
  const headers = ['Timestamp', 'User/Actor', 'Action', 'Entity ID', 'New State', 'Status'];
  const rows = logs.map(l => [
    l.created_at || l.timestamp || '',
    l.user_id || l.actor_id || 'System',
    l.action || '',
    l.entity_id || '',
    (l.new_state || '').toString().replace(/,/g, ';'),
    (l.action !== 'error' && l.action !== 'ERROR') ? 'Success' : 'Failed',
  ]);
  const csv = [headers, ...rows].map(r => r.map(v => `"${v}"`).join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = `audit_logs_${Date.now()}.csv`;
  a.click(); URL.revokeObjectURL(url);
}

/* ── Main Page ─────────────────────────────────────────── */
export default function Audit() {
  const [logs, setLogs]                 = useState([]);
  const [loading, setLoading]           = useState(true);
  const [search, setSearch]             = useState('');
  const [sFocused, setSFocused]         = useState(false);
  const [filterAction, setFilterAction] = useState('ALL');
  const [filterOpen, setFilterOpen]     = useState(false);
  const [selectedLog, setSelectedLog]   = useState(null);
  const filterRef                       = useRef(null);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e) => { if (filterRef.current && !filterRef.current.contains(e.target)) setFilterOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const r = await fetchAuditLogs({ limit: 500 });
      setLogs(Array.isArray(r) ? r : []);
    } catch {
      setLogs([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const filteredLogs = logs.filter(log => {
    if (filterAction !== 'ALL') {
      const group = ACTION_MAP[log.action]?.label?.toUpperCase() || log.action;
      if (group !== filterAction) return false;
    }
    if (search) {
      const q = search.toLowerCase();
      return (
        (log.user_id || log.actor_id || '').toString().toLowerCase().includes(q) ||
        (log.entity_id || '').toString().toLowerCase().includes(q) ||
        (log.action || '').toLowerCase().includes(q)
      );
    }
    return true;
  });

  const counts = {
    total:    logs.length,
    approved: logs.filter(l => ACTION_MAP[l.action]?.label === 'Approve').length,
    rejected: logs.filter(l => ACTION_MAP[l.action]?.label === 'Reject').length,
    system:   logs.filter(l => (!l.user_id && !l.actor_id) || l.actor_id === 'System').length,
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#F8FAFC' }}>
      <Navbar title="Audit Logs" subtitle="Track all user actions and system events" />

      <div style={{ padding: '24px 28px', maxWidth: 1280, margin: '0 auto', width: '100%', flex: 1, display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>

        {/* ── Summary Cards ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 24 }}>
          <SummaryCard label="Total Actions"   val={counts.total}    color="#2563EB" bg="#DBEAFE" icon={FileText}      accentColor="#2563EB" />
          <SummaryCard label="Approved"        val={counts.approved} color="#16A34A" bg="#DCFCE7" icon={CheckCircle2}  accentColor="#16A34A" />
          <SummaryCard label="Rejected"        val={counts.rejected} color="#DC2626" bg="#FEE2E2" icon={XCircle}       accentColor="#DC2626" />
          <SummaryCard label="System Actions"  val={counts.system}   color="#7C3AED" bg="#EDE9FE" icon={AlertCircle}   accentColor="#7C3AED" />
        </div>

        {/* ── Toolbar: Search | Filter | Buttons ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>

          {/* Search — grows, never overflows */}
          <div style={{
            position: 'relative', flex: 1, minWidth: 0,
            background: '#FFFFFF', border: `1.5px solid ${sFocused ? '#2563EB' : '#E5E7EB'}`,
            borderRadius: 10, boxShadow: sFocused ? '0 0 0 3px rgba(37,99,235,0.08)' : '0 1px 2px rgba(15,23,42,0.04)',
            transition: 'all 150ms ease', overflow: 'hidden',
          }}>
            <Search size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: sFocused ? '#2563EB' : '#94A3B8', transition: 'color 150ms', pointerEvents: 'none' }} />
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              onFocus={() => setSFocused(true)}
              onBlur={() => setSFocused(false)}
              placeholder="Search by user, action, or ID..."
              style={{
                width: '100%', height: 42, padding: '0 38px 0 40px',
                boxSizing: 'border-box',
                border: 'none', outline: 'none',
                fontSize: 14, color: '#0F172A', background: 'transparent',
              }}
            />
            {search && (
              <button onClick={() => setSearch('')} style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: '#94A3B8', display: 'flex', padding: 4 }}>
                <X size={14} />
              </button>
            )}
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 28, background: '#E5E7EB', flexShrink: 0 }} />

          {/* Custom Filter Dropdown */}
          <div ref={filterRef} style={{ position: 'relative', flexShrink: 0 }}>
            <button
              onClick={() => setFilterOpen(o => !o)}
              style={{
                height: 42, padding: '0 14px', borderRadius: 10,
                border: `1.5px solid ${filterOpen ? '#2563EB' : '#E5E7EB'}`,
                background: filterOpen ? '#F0F5FF' : '#FFFFFF',
                display: 'flex', alignItems: 'center', gap: 8,
                fontSize: 13, fontWeight: 600, color: filterOpen ? '#2563EB' : '#334155',
                cursor: 'pointer', whiteSpace: 'nowrap', minWidth: 148,
                boxShadow: filterOpen ? '0 0 0 3px rgba(37,99,235,0.08)' : '0 1px 2px rgba(15,23,42,0.04)',
                transition: 'all 150ms ease',
              }}
            >
              <Filter size={14} style={{ flexShrink: 0 }} />
              <span style={{ flex: 1, textAlign: 'left' }}>
                {filterAction === 'ALL' ? 'All Actions' : filterAction.charAt(0) + filterAction.slice(1).toLowerCase()}
              </span>
              <ChevronDown size={14} style={{ transform: filterOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 200ms ease', flexShrink: 0 }} />
            </button>

            {filterOpen && (
              <div style={{
                position: 'absolute', top: 'calc(100% + 6px)', left: 0, zIndex: 999,
                background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12,
                boxShadow: '0 8px 24px rgba(15,23,42,0.12), 0 2px 8px rgba(15,23,42,0.06)',
                minWidth: 180, overflow: 'hidden',
                animation: 'dropIn 150ms ease',
              }}>
                {/* Dropdown header */}
                <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid #F1F5F9' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Filter by Action</div>
                </div>
                {[
                  { key: 'ALL',      label: 'All Actions', color: '#334155', bg: '#F1F5F9', dot: '#94A3B8' },
                  { key: 'UPLOAD',   label: 'Upload',      color: '#2563EB', bg: '#DBEAFE', dot: '#2563EB' },
                  { key: 'APPROVE',  label: 'Approve',     color: '#16A34A', bg: '#DCFCE7', dot: '#16A34A' },
                  { key: 'REJECT',   label: 'Reject',      color: '#DC2626', bg: '#FEE2E2', dot: '#DC2626' },
                  { key: 'EDIT',     label: 'Edit',        color: '#2563EB', bg: '#DBEAFE', dot: '#2563EB' },
                  { key: 'OCR',      label: 'OCR',         color: '#9333EA', bg: '#F3E8FF', dot: '#9333EA' },
                  { key: 'REGISTER', label: 'Register',    color: '#0284C7', bg: '#E0F2FE', dot: '#0284C7' },
                ].map(opt => (
                  <button
                    key={opt.key}
                    onClick={() => { setFilterAction(opt.key); setFilterOpen(false); }}
                    style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 10,
                      padding: '10px 14px', border: 'none', cursor: 'pointer', textAlign: 'left',
                      background: filterAction === opt.key ? opt.bg : 'transparent',
                      transition: 'background 100ms ease',
                    }}
                    onMouseEnter={e => { if (filterAction !== opt.key) e.currentTarget.style.background = '#F8FAFC'; }}
                    onMouseLeave={e => { if (filterAction !== opt.key) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <span style={{ width: 8, height: 8, borderRadius: '50%', background: opt.dot, flexShrink: 0 }} />
                    <span style={{ fontSize: 13, fontWeight: filterAction === opt.key ? 700 : 500, color: filterAction === opt.key ? opt.color : '#334155', flex: 1 }}>{opt.label}</span>
                    {filterAction === opt.key && <span style={{ fontSize: 11, fontWeight: 700, color: opt.color, background: opt.bg, padding: '2px 7px', borderRadius: 5 }}>✓</span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 28, background: '#E5E7EB', flexShrink: 0 }} />

          {/* Action buttons — flexShrink: 0 guarantees full render */}
          <div style={{ display: 'flex', gap: 8, flexShrink: 0, alignItems: 'center' }}>
            <button
              onClick={() => exportCSV(filteredLogs)}
              disabled={loading || filteredLogs.length === 0}
              style={{
                height: 42, padding: '0 16px', borderRadius: 10,
                background: '#FFFFFF', border: '1.5px solid #E5E7EB',
                display: 'flex', alignItems: 'center', gap: 7,
                fontSize: 13, fontWeight: 600, color: '#334155',
                cursor: (loading || filteredLogs.length === 0) ? 'not-allowed' : 'pointer',
                whiteSpace: 'nowrap', transition: 'all 150ms ease',
                opacity: (loading || filteredLogs.length === 0) ? 0.5 : 1,
                boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
              }}
              onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = '#F8FAFC'; e.currentTarget.style.borderColor = '#CBD5E1'; }}}
              onMouseLeave={e => { e.currentTarget.style.background = '#FFFFFF'; e.currentTarget.style.borderColor = '#E5E7EB'; }}
            >
              <Download size={14} />
              Export CSV
            </button>
            <button
              onClick={load}
              disabled={loading}
              style={{
                height: 42, padding: '0 16px', borderRadius: 10,
                background: '#FFFFFF', border: '1.5px solid #E5E7EB',
                display: 'flex', alignItems: 'center', gap: 7,
                fontSize: 13, fontWeight: 600, color: '#334155',
                cursor: loading ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap',
                transition: 'all 150ms ease', opacity: loading ? 0.6 : 1,
                boxShadow: '0 1px 2px rgba(15,23,42,0.04)',
              }}
              onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = '#F8FAFC'; e.currentTarget.style.borderColor = '#CBD5E1'; }}}
              onMouseLeave={e => { e.currentTarget.style.background = '#FFFFFF'; e.currentTarget.style.borderColor = '#E5E7EB'; }}
            >
              <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              Refresh
            </button>
          </div>
        </div>

        {/* ── Log Table ── */}
        <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 14, flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 1px 4px rgba(15,23,42,0.05)' }}>

          {/* Table header */}
          <div style={{ display: 'flex', alignItems: 'center', height: 46, background: '#F8FAFC', padding: '0 20px', borderBottom: '1px solid #E5E7EB', fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', flexShrink: 0 }}>
            <div style={{ width: 165 }}>Timestamp</div>
            <div style={{ width: 130 }}>User</div>
            <div style={{ width: 110 }}>Action</div>
            <div style={{ width: 110 }}>Entity</div>
            <div style={{ flex: 1 }}>Changes</div>
            <div style={{ width: 100 }}>Status</div>
            <div style={{ width: 32 }} />
          </div>

          {/* Rows */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {loading ? (
              <div style={{ padding: 56, textAlign: 'center' }}>
                <RefreshCw size={24} color="#CBD5E1" style={{ animation: 'spin 1s linear infinite', marginBottom: 12 }} />
                <div style={{ fontSize: 14, color: '#94A3B8', fontWeight: 500 }}>Loading audit logs…</div>
              </div>
            ) : filteredLogs.length === 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 260, gap: 8 }}>
                <Filter size={36} color="#CBD5E1" strokeWidth={1.5} />
                <div style={{ fontSize: 15, fontWeight: 700, color: '#0F172A', marginTop: 4 }}>No logs found</div>
                <div style={{ fontSize: 13, color: '#94A3B8' }}>Try adjusting your search or filter</div>
              </div>
            ) : (
              filteredLogs.map((log, i) => {
                const conf      = ACTION_MAP[log.action] || { label: log.action || 'Event', color: '#64748B', bg: '#F1F5F9' };
                const isSuccess = log.action !== 'error' && log.action !== 'ERROR';

                let preview = '—';
                if (log.new_state && log.previous_state) preview = 'Value updated';
                else if (log.new_state)                  preview = `Set to ${log.new_state}`;
                else if (typeof log.metadata === 'string') preview = log.metadata;

                return (
                  <div
                    key={i}
                    onClick={() => setSelectedLog(log)}
                    style={{
                      display: 'flex', alignItems: 'center', height: 54, padding: '0 20px',
                      borderBottom: '1px solid #F1F5F9', cursor: 'pointer', transition: 'background 120ms ease',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#F8FAFC'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <div style={{ width: 165, fontSize: 12, color: '#94A3B8', fontVariantNumeric: 'tabular-nums', fontFamily: 'monospace' }}>{fmtTs(log.created_at || log.timestamp)}</div>
                    <div style={{ width: 130, fontSize: 14, fontWeight: 700, color: '#0F172A' }}>{log.user_id || log.actor_id || 'System'}</div>
                    <div style={{ width: 110 }}>
                      <span style={{ padding: '3px 10px', borderRadius: 999, fontSize: 12, fontWeight: 700, background: conf.bg, color: conf.color }}>{conf.label}</span>
                    </div>
                    <div style={{ width: 110, fontSize: 13, color: '#475569', fontFamily: 'monospace' }}>{log.entity_id || '—'}</div>
                    <div style={{ flex: 1, fontSize: 13, color: '#64748B', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', paddingRight: 16 }}>{preview}</div>
                    <div style={{ width: 100 }}>
                      <span style={{
                        padding: '3px 10px', borderRadius: 999, fontSize: 12, fontWeight: 700,
                        background: isSuccess ? '#DCFCE7' : '#FEE2E2',
                        color:      isSuccess ? '#16A34A'  : '#DC2626',
                      }}>
                        {isSuccess ? 'Success' : 'Failed'}
                      </span>
                    </div>
                    <div style={{ width: 32, textAlign: 'right' }}>
                      <ChevronRight size={15} color="#CBD5E1" />
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Footer count */}
          {!loading && filteredLogs.length > 0 && (
            <div style={{ height: 40, borderTop: '1px solid #F1F5F9', background: '#F8FAFC', display: 'flex', alignItems: 'center', padding: '0 20px' }}>
              <span style={{ fontSize: 12, color: '#94A3B8', fontWeight: 500 }}>
                Showing <strong style={{ color: '#334155' }}>{filteredLogs.length}</strong> of <strong style={{ color: '#334155' }}>{logs.length}</strong> log entries
              </span>
            </div>
          )}
        </div>
      </div>

      <DetailDrawer log={selectedLog} isOpen={!!selectedLog} onClose={() => setSelectedLog(null)} />
    </div>
  );
}
