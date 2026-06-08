/* PanInfoSection — clean light card matching Aadhaar visual */

import { useState } from 'react';
import { Copy, Check, CreditCard, CheckCircle2, AlertCircle } from 'lucide-react';

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

const isValidPAN = (v) => /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test((v || '').toUpperCase());

function Field({ label, value, mono, copyable, validate, empty = 'Not extracted' }) {
  const [copied, copy] = useCopy(value);
  const valid = validate && value ? validate(value) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span className="e-field-label">{label}</span>
        {valid === true  && <span style={{ fontSize: 11, fontWeight: 600, color: '#16a34a', display: 'flex', alignItems: 'center', gap: 3 }}><CheckCircle2 size={11} /> Valid</span>}
        {valid === false && <span style={{ fontSize: 11, fontWeight: 600, color: '#dc2626', display: 'flex', alignItems: 'center', gap: 3 }}><AlertCircle size={11} /> Invalid</span>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className={`e-field-value ${mono ? 'mono' : ''} ${!value ? 'muted' : ''}`} style={{ flex: 1 }}>
          {value || empty}
        </span>
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

export default function PanInfoSection({ user }) {
  // ── STRICT: read ONLY from the pan sub-object. NEVER fall back to
  // user.extracted_name / user.name — those may contain Aadhaar data.
  const pan    = user?.pan || {};
  const name   = pan.name;
  const number = pan.pan_number || user?.pan_number || user?.original_pan;
  const dob    = pan.dob;
  // confidence already 0–100 from backend
  const conf   = (pan.confidence != null ? pan.confidence : (user?.pan_confidence || 0)) / 100;

  const panValid  = number ? isValidPAN(number) : null;
  const hasData   = name || number;
  const badgeClass = panValid === true ? 'badge-green' : panValid === false ? 'badge-red' : hasData ? 'badge-blue' : 'badge-gray';
  const badgeLabel = panValid === true ? 'Valid' : panValid === false ? 'Invalid Format' : hasData ? 'Extracted' : 'Pending';

  return (
    <div className="e-card">
      <div className="e-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#eff6ff', border: '1px solid #bfdbfe',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <CreditCard size={14} color="#2563eb" />
          </div>
          <span className="e-card-title">PAN Information</span>
        </div>
        <span className={`badge ${badgeClass}`}>{badgeLabel}</span>
      </div>

      <div className="e-card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <Field label="Full Name" value={name} copyable />
        <Field label="PAN Number" value={number} mono copyable validate={isValidPAN} />
        <Field label="Date of Birth" value={dob} />
        <div className="e-divider" style={{ margin: '4px 0' }} />
        <div>
          <div className="e-field-label" style={{ marginBottom: 6 }}>OCR Confidence</div>
          <ConfBar value={conf} />
        </div>
      </div>
    </div>
  );
}
