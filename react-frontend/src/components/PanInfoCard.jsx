import { useState } from 'react';
import { Copy, Check, CreditCard, Eye, EyeOff, CheckCircle2 } from 'lucide-react';

function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 85 ? '#10b981' : pct >= 60 ? '#f59e0b' : '#ef4444';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ flex: 1, height: 5, borderRadius: 3, background: '#1e293b', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3, transition: 'width 0.8s cubic-bezier(0.4,0,0.2,1)' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 36 }}>{pct}%</span>
    </div>
  );
}

function FieldRow({ label, value, monospace, copyable, validate }) {
  const [copied, setCopied] = useState(false);
  const isValid = validate ? validate(value) : null;

  const handleCopy = () => {
    if (value) {
      navigator.clipboard.writeText(value).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {label}
        </span>
        {isValid !== null && (
          <span style={{ fontSize: 11, fontWeight: 700, color: isValid ? '#10b981' : '#ef4444' }}>
            {isValid ? '✓ Valid' : '✗ Invalid'}
          </span>
        )}
      </div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: '#0f172a', border: '1px solid #1e293b',
        borderRadius: 10, padding: '10px 14px', minHeight: 44,
      }}>
        <span style={{
          flex: 1, fontSize: 14, fontWeight: 600, color: value ? '#f1f5f9' : '#475569',
          fontFamily: monospace ? "'Roboto Mono', monospace" : 'inherit',
          letterSpacing: monospace ? '0.1em' : 'inherit',
          fontStyle: !value ? 'italic' : 'normal',
        }}>
          {value || 'Not extracted'}
        </span>
        {isValid && <CheckCircle2 size={14} color="#10b981" />}
        {copyable && value && (
          <button onClick={handleCopy} style={{ background: 'none', border: 'none', cursor: 'pointer', color: copied ? '#10b981' : '#64748b', padding: 0, display: 'flex', alignItems: 'center', transition: 'color 0.2s' }}>
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }) {
  const configs = {
    verified:     { label: 'Verified',  bg: 'rgba(16,185,129,0.12)',  color: '#10b981', border: 'rgba(16,185,129,0.25)' },
    extracted:    { label: 'Extracted', bg: 'rgba(99,102,241,0.12)',  color: '#818cf8', border: 'rgba(99,102,241,0.25)' },
    needs_review: { label: 'Review',    bg: 'rgba(245,158,11,0.12)',  color: '#f59e0b', border: 'rgba(245,158,11,0.25)' },
    failed:       { label: 'Failed',    bg: 'rgba(239,68,68,0.12)',   color: '#f87171', border: 'rgba(239,68,68,0.25)' },
  };
  const cfg = configs[status] || configs.extracted;
  return (
    <span style={{
      fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: 20,
      background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
      textTransform: 'uppercase', letterSpacing: '0.06em',
    }}>
      {cfg.label}
    </span>
  );
}

const isValidPAN = (v) => /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test((v || '').toUpperCase());

export default function PanInfoCard({ user }) {
  const name   = user?.pan_name || user?.extracted_name || user?.name || user?.original_name;
  const number = user?.pan_number || user?.extracted_pan || user?.original_pan;
  const dob    = user?.extracted_dob || user?.dob;
  const conf   = user?.pan_confidence || user?.confidence / 100 || 0;

  const panValid = number ? isValidPAN(number) : null;
  const extractionStatus = number ? (panValid ? 'verified' : 'needs_review') : 'needs_review';

  return (
    <div style={cardStyle}>
      {/* Card Header */}
      <div style={cardHeaderStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: 'linear-gradient(135deg, rgba(99,102,241,0.2), rgba(79,70,229,0.1))',
            border: '1px solid rgba(99,102,241,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <CreditCard size={17} color="#818cf8" />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>PAN Information</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>Income Tax Department — Government of India</div>
          </div>
        </div>
        <StatusBadge status={extractionStatus} />
      </div>

      {/* Fields Grid */}
      <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div style={{ gridColumn: '1 / -1' }}>
          <FieldRow label="Full Name (OCR)" value={name} copyable />
        </div>
        <FieldRow
          label="PAN Number"
          value={number}
          monospace
          copyable
          validate={v => v ? isValidPAN(v) : null}
        />
        <FieldRow label="Date of Birth" value={dob} />
      </div>

      {/* Confidence Footer */}
      <div style={{ padding: '12px 20px', borderTop: '1px solid #1e293b' }}>
        <div style={{ fontSize: 11, color: '#64748b', fontWeight: 600, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          OCR Extraction Confidence
        </div>
        <ConfidenceBar value={conf} />
      </div>
    </div>
  );
}

const cardStyle = {
  background: '#0f172a',
  border: '1px solid #1e293b',
  borderRadius: 16,
  overflow: 'hidden',
};

const cardHeaderStyle = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '16px 20px',
  borderBottom: '1px solid #1e293b',
  background: 'linear-gradient(135deg, rgba(99,102,241,0.05) 0%, transparent 100%)',
};
