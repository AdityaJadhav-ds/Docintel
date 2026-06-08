import { Clock, Upload, Cpu, CheckCircle2, XCircle, SkipForward, RefreshCw } from 'lucide-react';

const EVENT_ICONS = {
  uploaded:   { Icon: Upload,       color: '#818cf8', bg: 'rgba(99,102,241,0.12)' },
  ocr:        { Icon: Cpu,          color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  approved:   { Icon: CheckCircle2, color: '#10b981', bg: 'rgba(16,185,129,0.12)' },
  rejected:   { Icon: XCircle,      color: '#ef4444', bg: 'rgba(239,68,68,0.12)'  },
  skipped:    { Icon: SkipForward,  color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  reprocessed:{ Icon: RefreshCw,    color: '#38bdf8', bg: 'rgba(56,189,248,0.12)' },
};

function TimelineEvent({ icon, title, subtitle, time, isLast }) {
  const cfg = EVENT_ICONS[icon] || EVENT_ICONS.uploaded;
  const { Icon } = cfg;

  return (
    <div style={{ display: 'flex', gap: 14, position: 'relative' }}>
      {/* Icon column */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0, flexShrink: 0 }}>
        <div style={{
          width: 34, height: 34, borderRadius: '50%',
          background: cfg.bg, border: `1px solid ${cfg.color}30`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1, flexShrink: 0,
        }}>
          <Icon size={15} color={cfg.color} />
        </div>
        {!isLast && (
          <div style={{ width: 1, flex: 1, minHeight: 20, background: '#1e293b', marginTop: 4 }} />
        )}
      </div>

      {/* Content */}
      <div style={{ paddingBottom: isLast ? 0 : 20, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: '#f1f5f9' }}>{title}</div>
          {time && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
              <Clock size={11} color="#64748b" />
              <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>{time}</span>
            </div>
          )}
        </div>
        {subtitle && (
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 4, lineHeight: 1.5 }}>{subtitle}</div>
        )}
      </div>
    </div>
  );
}

export default function AuditTimeline({ user }) {
  const fmt = (ts) => {
    if (!ts) return null;
    try {
      return new Date(ts).toLocaleString('en-IN', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      });
    } catch { return ts; }
  };

  const wfState = user?.workflow_state || user?.status;
  const events = [];

  // Upload event
  events.push({
    icon: 'uploaded',
    title: 'Documents Uploaded',
    subtitle: `KYC documents submitted for ${user?.original_name || user?.name || 'user'}.`,
    time: fmt(user?.created_at),
  });

  // OCR event
  if (user?.extracted_name || user?.aadhaar_number || user?.pan_number) {
    events.push({
      icon: 'ocr',
      title: 'OCR Extraction Complete',
      subtitle: `Fields extracted with ${user?.confidence || 0}% confidence.`,
      time: user?.created_at ? fmt(new Date(new Date(user.created_at).getTime() + 15000).toISOString()) : null,
    });
  }

  // Status event
  if (wfState && !['UPLOADED', 'PROCESSING', 'PENDING'].includes(wfState)) {
    const iconMap = {
      VERIFIED: 'approved',
      APPROVED: 'approved',
      REJECTED: 'rejected',
      REVIEW_REQUIRED: 'skipped',
    };
    const labelMap = {
      VERIFIED: 'Verification Approved',
      APPROVED: 'Verification Approved',
      REJECTED: 'Verification Rejected',
      REVIEW_REQUIRED: 'Sent for Manual Review',
    };
    events.push({
      icon: iconMap[wfState] || 'uploaded',
      title: labelMap[wfState] || `Status: ${wfState}`,
      subtitle: 'Manual review action by compliance team.',
      time: fmt(user?.updated_at),
    });
  }

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 16, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid #1e293b' }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>Audit Trail</div>
        <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>{events.length} recorded event{events.length !== 1 ? 's' : ''}</div>
      </div>

      {/* Timeline */}
      <div style={{ padding: '16px 20px' }}>
        {events.map((evt, i) => (
          <TimelineEvent key={i} {...evt} isLast={i === events.length - 1} />
        ))}
      </div>
    </div>
  );
}
