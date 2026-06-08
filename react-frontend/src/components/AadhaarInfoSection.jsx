/* AadhaarInfoSection — clean light card */

import { useState } from 'react';
import { Copy, Check, Eye, EyeOff, ShieldCheck } from 'lucide-react';

function useCopy(value) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    if (!value) return;
    navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    });
  };
  return [copied, copy];
}

function Field({ label, value, mono, masked, copyable, empty = 'Not extracted' }) {
  const [show, setShow] = useState(false);
  const [copied, copy] = useCopy(value);

  const displayVal = masked && !show
    ? `XXXX XXXX ${(value || '').replace(/\s/g, '').slice(-4)}`
    : value;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span className="e-field-label">{label}</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span
          className={`e-field-value ${mono ? 'mono' : ''} ${!value ? 'muted' : ''}`}
          style={{ flex: 1 }}
        >
          {displayVal || empty}
        </span>
        {masked && value && (
          <button className="copy-btn" onClick={() => setShow(s => !s)} title={show ? 'Hide' : 'Reveal'}>
            {show ? <EyeOff size={13} /> : <Eye size={13} />}
          </button>
        )}
        {copyable && value && (
          <button className="copy-btn" onClick={copy} title="Copy">
            {copied ? <Check size={13} color="#16a34a" /> : <Copy size={13} />}
          </button>
        )}
      </div>
    </div>
  );
}

function ConfBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 85 ? '#16a34a' : pct >= 60 ? '#d97706' : '#dc2626';
  return (
    <div className="conf-bar-wrap">
      <div className="conf-bar-track">
        <div className="conf-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="conf-bar-label" style={{ color }}>{pct}%</span>
    </div>
  );
}

export default function AadhaarInfoSection({ user }) {
  // ── STRICT: read ONLY from the aadhaar sub-object. NEVER fall back to
  // user.extracted_name / user.name — those may contain PAN data.
  const aadhaar = user?.aadhaar || {};
  const name    = aadhaar.name;
  const number  = aadhaar.aadhaar_number || user?.aadhaar_number || user?.original_aadhaar;
  const dob     = aadhaar.dob;
  const gender  = user?.gender;
  // confidence already 0–100 from backend
  const conf    = (aadhaar.confidence != null ? aadhaar.confidence : (user?.aadhaar_confidence || 0)) / 100;

  const hasData = !!(name || number || dob);

  return (
    <div className="e-card">
      <div className="e-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#f0fdf4', border: '1px solid #bbf7d0',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <ShieldCheck size={14} color="#16a34a" />
          </div>
          <span className="e-card-title">Aadhaar Information</span>
        </div>
        <span className={`badge ${hasData ? 'badge-green' : 'badge-gray'}`}>
          {hasData ? 'Extracted' : 'Pending'}
        </span>
      </div>

      <div className="e-card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Full Name" value={name} copyable />
        <Field label="Aadhaar Number" value={number} mono masked copyable />
        <Field label="Date of Birth" value={dob} />
        {gender && <Field label="Gender" value={gender} />}
        <div className="e-divider" style={{ margin: '4px 0' }} />
        <div>
          <div className="e-field-label" style={{ marginBottom: 6 }}>OCR Confidence</div>
          <ConfBar value={conf} />
        </div>
      </div>
    </div>
  );
}
