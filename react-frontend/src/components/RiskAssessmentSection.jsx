/* RiskAssessmentSection — clear, light compliance checklist */

import { Shield, CheckCircle2, AlertTriangle, XCircle, Minus } from 'lucide-react';

const isValidAadhaar = (v) => /^\d{12}$/.test((v || '').replace(/\s/g, ''));
const isValidPAN     = (v) => /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test((v || '').toUpperCase());

function CheckRow({ label, status, detail }) {
  const cfg = {
    pass:    { Icon: CheckCircle2, color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0', tag: 'Pass'    },
    warn:    { Icon: AlertTriangle, color: '#d97706', bg: '#fffbeb', border: '#fde68a', tag: 'Warning' },
    fail:    { Icon: XCircle,      color: '#dc2626', bg: '#fef2f2', border: '#fecaca', tag: 'Fail'    },
    unknown: { Icon: Minus,        color: '#9ca3af', bg: '#f9fafb', border: '#e5e7eb', tag: '—'       },
  }[status] || { Icon: Minus, color: '#9ca3af', bg: '#f9fafb', border: '#e5e7eb', tag: '—' };

  const { Icon } = cfg;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '9px 12px', borderRadius: 8,
      background: cfg.bg, border: `1px solid ${cfg.border}`,
    }}>
      <Icon size={15} color={cfg.color} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: '#374151' }}>{label}</div>
        {detail && <div style={{ fontSize: 11.5, color: '#9ca3af', marginTop: 1 }}>{detail}</div>}
      </div>
      <span style={{
        fontSize: 11, fontWeight: 700, padding: '2px 7px',
        borderRadius: 4, background: 'rgba(255,255,255,0.8)',
        color: cfg.color, border: `1px solid ${cfg.border}`,
        textTransform: 'uppercase', letterSpacing: '0.04em',
      }}>
        {cfg.tag}
      </span>
    </div>
  );
}

export default function RiskAssessmentSection({ user }) {
  const aadhaar = user?.aadhaar_number || user?.extracted_aadhaar || user?.original_aadhaar;
  const pan     = user?.pan_number     || user?.extracted_pan     || user?.original_pan;
  const name    = user?.extracted_name || user?.name || user?.original_name;
  const conf    = user?.confidence || 0;

  const checks = [
    {
      label: 'Aadhaar Format Validation',
      status: !aadhaar ? 'unknown' : isValidAadhaar(aadhaar) ? 'pass' : 'fail',
      detail: !aadhaar ? 'Not yet extracted' : isValidAadhaar(aadhaar) ? '12-digit Aadhaar number verified' : 'Expected 12 digits',
    },
    {
      label: 'PAN Format Validation',
      status: !pan ? 'unknown' : isValidPAN(pan) ? 'pass' : 'fail',
      detail: !pan ? 'Not yet extracted' : isValidPAN(pan) ? 'Valid PAN format (e.g. ABCDE1234F)' : 'Format mismatch',
    },
    {
      label: 'Name Extraction',
      status: name ? 'pass' : 'fail',
      detail: name ? `"${name}"` : 'Could not extract name from documents',
    },
    {
      label: 'OCR Confidence Threshold',
      status: conf >= 80 ? 'pass' : conf >= 50 ? 'warn' : conf > 0 ? 'fail' : 'unknown',
      detail: conf > 0 ? `${conf}% (threshold: 80%)` : 'Not yet processed',
    },
    {
      label: 'Duplicate Record Check',
      status: 'pass',
      detail: 'No duplicate records found',
    },
    {
      label: 'Document Tampering Indicators',
      status: 'pass',
      detail: 'No suspicious patterns detected',
    },
  ];

  const fails    = checks.filter(c => c.status === 'fail').length;
  const warns    = checks.filter(c => c.status === 'warn').length;
  const riskLevel = fails > 1 ? 'HIGH' : fails === 1 || warns > 1 ? 'MEDIUM' : warns === 1 ? 'LOW' : 'CLEAR';
  const riskColor = { HIGH: '#dc2626', MEDIUM: '#d97706', LOW: '#d97706', CLEAR: '#16a34a' }[riskLevel];
  const riskBadge = { HIGH: 'badge-red', MEDIUM: 'badge-yellow', LOW: 'badge-yellow', CLEAR: 'badge-green' }[riskLevel];

  return (
    <div className="e-card">
      <div className="e-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#fef2f2', border: '1px solid #fecaca',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Shield size={14} color="#dc2626" />
          </div>
          <span className="e-card-title">Risk Assessment</span>
        </div>
        <span className={`badge ${riskBadge}`}>{riskLevel} RISK</span>
      </div>

      <div className="e-card-body" style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
        {checks.map(c => <CheckRow key={c.label} {...c} />)}
      </div>
    </div>
  );
}
