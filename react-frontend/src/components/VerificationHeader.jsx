import { User, Calendar, Hash, CheckCircle2, AlertTriangle, XCircle, Clock } from 'lucide-react';

function StatusChip({ label, color, bg, border }) {
  return (
    <span style={{
      fontSize: 12, fontWeight: 700, padding: '4px 12px', borderRadius: 20,
      background: bg, color, border: `1px solid ${border}`,
      textTransform: 'uppercase', letterSpacing: '0.06em',
    }}>
      {label}
    </span>
  );
}

function MetaChip({ icon: Icon, label, value }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: 10, padding: '6px 12px',
    }}>
      <Icon size={13} color="#64748b" />
      <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>{label}:</span>
      <span style={{ fontSize: 12, color: '#94a3b8', fontWeight: 700 }}>{value}</span>
    </div>
  );
}

export default function VerificationHeader({ user }) {
  const name = user?.original_name || user?.full_name || user?.name || user?.extracted_name || 'Unknown';
  const id = user?.id;
  const status = user?.workflow_state || user?.status || 'PENDING';
  const conf = user?.confidence || 0;
  const uploadedAt = user?.created_at;
  const dob = user?.dob;

  const statusConfigs = {
    VERIFIED: { label: 'Verified',       color: '#10b981', bg: 'rgba(16,185,129,0.12)',  border: 'rgba(16,185,129,0.25)',  Icon: CheckCircle2 },
    APPROVED: { label: 'Verified',       color: '#10b981', bg: 'rgba(16,185,129,0.12)',  border: 'rgba(16,185,129,0.25)',  Icon: CheckCircle2 },
    REJECTED: { label: 'Rejected',       color: '#ef4444', bg: 'rgba(239,68,68,0.12)',   border: 'rgba(239,68,68,0.25)',   Icon: XCircle },
    REVIEW_REQUIRED: { label: 'Review',  color: '#f59e0b', bg: 'rgba(245,158,11,0.12)',  border: 'rgba(245,158,11,0.25)',  Icon: AlertTriangle },
    PROCESSING: { label: 'Processing',   color: '#818cf8', bg: 'rgba(99,102,241,0.12)',  border: 'rgba(99,102,241,0.25)',  Icon: Clock },
    UPLOADED:   { label: 'Pending',      color: '#64748b', bg: 'rgba(100,116,139,0.12)', border: 'rgba(100,116,139,0.25)', Icon: Clock },
    PENDING:    { label: 'Pending',      color: '#64748b', bg: 'rgba(100,116,139,0.12)', border: 'rgba(100,116,139,0.25)', Icon: Clock },
  };
  const cfg = statusConfigs[status] || statusConfigs.PENDING;
  const { Icon: StatusIcon } = cfg;

  const riskLevel = conf >= 85 ? 'Low' : conf >= 60 ? 'Medium' : conf > 0 ? 'High' : 'Unknown';
  const riskColor = conf >= 85 ? '#10b981' : conf >= 60 ? '#f59e0b' : '#ef4444';

  const fmtDate = (ts) => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }); }
    catch { return ts; }
  };

  // Get initials for avatar
  const initials = name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');

  return (
    <div style={{
      background: 'linear-gradient(135deg, #0f172a 0%, #0a0f1e 100%)',
      border: '1px solid #1e293b',
      borderRadius: 16, padding: '20px 24px',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Background accent */}
      <div style={{
        position: 'absolute', top: -40, right: -40, width: 180, height: 180, borderRadius: '50%',
        background: `radial-gradient(circle, ${cfg.bg} 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      <div style={{ display: 'flex', alignItems: 'center', gap: 20, position: 'relative' }}>
        {/* Avatar */}
        <div style={{
          width: 64, height: 64, borderRadius: 18, flexShrink: 0,
          background: 'linear-gradient(135deg, #1e3a5f, #1e293b)',
          border: `2px solid ${cfg.color}30`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 22, fontWeight: 800, color: cfg.color, letterSpacing: '-0.02em',
          boxShadow: `0 0 20px ${cfg.color}15`,
        }}>
          {initials || <User size={26} color="#64748b" />}
        </div>

        {/* Identity block */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 6 }}>
            <h2 style={{ fontSize: 20, fontWeight: 800, color: '#f1f5f9', margin: 0, letterSpacing: '-0.02em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {name}
            </h2>
            <StatusChip label={cfg.label} color={cfg.color} bg={cfg.bg} border={cfg.border} />
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {id && <MetaChip icon={Hash} label="ID" value={`#${id}`} />}
            {dob && <MetaChip icon={Calendar} label="DOB" value={dob} />}
            <MetaChip icon={StatusIcon} label="Risk" value={riskLevel} />
            <MetaChip icon={Clock} label="Uploaded" value={fmtDate(uploadedAt)} />
            {conf > 0 && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: '#1e293b', border: '1px solid #334155',
                borderRadius: 10, padding: '6px 12px',
              }}>
                <div style={{ width: 8, height: 8, borderRadius: '50%', background: riskColor }} />
                <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>OCR:</span>
                <span style={{ fontSize: 12, color: riskColor, fontWeight: 700 }}>{conf}%</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
