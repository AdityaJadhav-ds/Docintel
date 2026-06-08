/* ReviewHeader — sticky top info bar for the review workspace */

import { Calendar, Hash, Clock, TrendingUp } from 'lucide-react';

function StatusBadge({ state }) {
  const map = {
    VERIFIED:        { label: 'Verified',        cls: 'badge-green'  },
    APPROVED:        { label: 'Verified',        cls: 'badge-green'  },
    REJECTED:        { label: 'Rejected',         cls: 'badge-red'    },
    REVIEW_REQUIRED: { label: 'Manual Review',    cls: 'badge-yellow' },
    PROCESSING:      { label: 'Processing',       cls: 'badge-blue'   },
    UPLOADED:        { label: 'Pending Review',   cls: 'badge-gray'   },
    PENDING:         { label: 'Pending Review',   cls: 'badge-gray'   },
  };
  const cfg = map[state] || map.PENDING;
  return <span className={`badge ${cfg.cls}`}>{cfg.label}</span>;
}

function MetaPill({ icon: Icon, value }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 5,
      fontSize: 12.5, color: '#6b7280', fontWeight: 500,
    }}>
      <Icon size={12} color="#9ca3af" />
      {value}
    </div>
  );
}

function ConfidenceDisplay({ value }) {
  const pct = Math.round(value || 0);
  const color = pct >= 85 ? '#16a34a' : pct >= 60 ? '#d97706' : '#dc2626';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 80 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
        OCR Confidence
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ flex: 1, height: 4, borderRadius: 2, background: '#f3f4f6', overflow: 'hidden', minWidth: 60 }}>
          <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2, transition: 'width 0.6s ease' }} />
        </div>
        <span style={{ fontSize: 13, fontWeight: 700, color, minWidth: 30 }}>{pct}%</span>
      </div>
    </div>
  );
}

export default function ReviewHeader({ user }) {
  const name   = user?.original_name || user?.full_name || user?.name || user?.extracted_name || 'Unknown';
  const state  = user?.workflow_state || user?.status || 'PENDING';
  const dob    = user?.dob;
  const conf   = user?.confidence || 0;
  const id     = user?.id;

  const initials = name.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();

  const fmtDate = (ts) => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); }
    catch { return ts; }
  };

  return (
    <div style={{
      background: '#ffffff',
      border: '1px solid #e5e7eb',
      borderRadius: 14,
      padding: '16px 20px',
      boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {/* Avatar */}
        <div style={{
          width: 48, height: 48, borderRadius: 12,
          background: 'linear-gradient(135deg, #eff6ff, #dbeafe)',
          border: '1.5px solid #bfdbfe',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 16, fontWeight: 700, color: '#2563eb',
          flexShrink: 0, letterSpacing: '-0.02em',
        }}>
          {initials}
        </div>

        {/* Identity */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            <h2 style={{
              fontSize: 17, fontWeight: 700, color: '#111827',
              margin: 0, letterSpacing: '-0.02em',
              whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {name}
            </h2>
            <StatusBadge state={state} />
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {id      && <MetaPill icon={Hash}     value={`ID #${id}`} />}
            {dob     && <MetaPill icon={Calendar} value={`DOB: ${dob}`} />}
            <MetaPill icon={Clock} value={`Uploaded ${fmtDate(user?.created_at)}`} />
          </div>
        </div>

        {/* Confidence */}
        {conf > 0 && (
          <div style={{ flexShrink: 0, borderLeft: '1px solid #f3f4f6', paddingLeft: 20 }}>
            <ConfidenceDisplay value={conf} />
          </div>
        )}
      </div>
    </div>
  );
}
