/* AuditTimelineSection — light enterprise timeline */

import { Clock, Upload, Cpu, CheckCircle2, XCircle, SkipForward, RefreshCw } from 'lucide-react';

const ICONS = {
  uploaded:    { Icon: Upload,       color: '#6b7280', bg: '#f9fafb', border: '#e5e7eb'  },
  ocr:         { Icon: Cpu,          color: '#d97706', bg: '#fffbeb', border: '#fde68a'  },
  approved:    { Icon: CheckCircle2, color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0'  },
  rejected:    { Icon: XCircle,      color: '#dc2626', bg: '#fef2f2', border: '#fecaca'  },
  skipped:     { Icon: SkipForward,  color: '#d97706', bg: '#fffbeb', border: '#fde68a'  },
  reprocessed: { Icon: RefreshCw,    color: '#2563eb', bg: '#eff6ff', border: '#bfdbfe'  },
};

function Event({ icon, title, subtitle, time, isLast }) {
  const cfg = ICONS[icon] || ICONS.uploaded;
  const { Icon } = cfg;

  return (
    <div style={{ display: 'flex', gap: 12, position: 'relative' }}>
      {/* Icon + vertical line */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
        <div style={{
          width: 30, height: 30, borderRadius: '50%',
          background: cfg.bg, border: `1px solid ${cfg.border}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 1,
        }}>
          <Icon size={13} color={cfg.color} />
        </div>
        {!isLast && (
          <div style={{ width: 1, flex: 1, minHeight: 16, background: '#f3f4f6', marginTop: 4 }} />
        )}
      </div>

      {/* Content */}
      <div style={{ paddingBottom: isLast ? 0 : 16, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: '#111827' }}>{title}</span>
          {time && (
            <span style={{ fontSize: 11.5, color: '#9ca3af', fontWeight: 500, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 3 }}>
              <Clock size={10} /> {time}
            </span>
          )}
        </div>
        {subtitle && (
          <p style={{ margin: '3px 0 0', fontSize: 12.5, color: '#6b7280', lineHeight: 1.5 }}>{subtitle}</p>
        )}
      </div>
    </div>
  );
}

export default function AuditTimelineSection({ user }) {
  const fmt = (ts) => {
    if (!ts) return null;
    try { return new Date(ts).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); }
    catch { return ts; }
  };

  const wf     = user?.workflow_state || user?.status;
  const events = [];

  events.push({
    icon: 'uploaded',
    title: 'Documents Submitted',
    subtitle: `KYC documents received for ${user?.original_name || user?.name || 'user'}.`,
    time: fmt(user?.created_at),
  });

  if (user?.extracted_name || user?.aadhaar_number || user?.pan_number) {
    events.push({
      icon: 'ocr',
      title: 'OCR Extraction Completed',
      subtitle: `Fields extracted with ${user?.confidence || 0}% confidence.`,
      time: user?.created_at ? fmt(new Date(new Date(user.created_at).getTime() + 15000).toISOString()) : null,
    });
  }

  if (wf && !['UPLOADED', 'PROCESSING', 'PENDING'].includes(wf)) {
    const iconMap  = { VERIFIED: 'approved', APPROVED: 'approved', REJECTED: 'rejected', REVIEW_REQUIRED: 'skipped' };
    const labelMap = { VERIFIED: 'Verification Approved', APPROVED: 'Verification Approved', REJECTED: 'Verification Rejected', REVIEW_REQUIRED: 'Sent for Manual Review' };
    events.push({
      icon:     iconMap[wf] || 'uploaded',
      title:    labelMap[wf] || wf,
      subtitle: 'Manual review action completed.',
      time:     fmt(user?.updated_at),
    });
  }

  return (
    <div className="e-card">
      <div className="e-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#f9fafb', border: '1px solid #e5e7eb',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Clock size={14} color="#6b7280" />
          </div>
          <span className="e-card-title">Audit Trail</span>
        </div>
        <span className="badge badge-gray">{events.length} event{events.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="e-card-body">
        {events.map((evt, i) => (
          <Event key={i} {...evt} isLast={i === events.length - 1} />
        ))}
      </div>
    </div>
  );
}
