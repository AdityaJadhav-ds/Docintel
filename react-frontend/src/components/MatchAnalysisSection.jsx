/* MatchAnalysisSection — cross-document field comparison */

import { GitCompare, Check, AlertTriangle, X } from 'lucide-react';

/* ── similarity helper ─────────────────────────────────── */
function norm(s)    { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function normId(s)  { return (s || '').replace(/\s/g, '').toUpperCase(); }
function normDob(s) {
  const d = (s || '').trim();
  if (d.length === 10 && (d[4] === '-' || d[4] === '/')) return d.replace(/\//g, '-');
  if (d.length === 10 && (d[2] === '-' || d[2] === '/')) {
    const p = d.replace(/\//g, '-').split('-');
    return `${p[2]}-${p[1]}-${p[0]}`;
  }
  return d;
}

function stringSimilarity(a, b) {
  const na = norm(a), nb = norm(b);
  if (!na || !nb)     return 0;
  if (na === nb)      return 1;
  const longer  = na.length >= nb.length ? na : nb;
  const shorter = na.length <  nb.length ? na : nb;
  let hits = 0;
  for (const ch of shorter) if (longer.includes(ch)) hits++;
  return hits / longer.length;
}

/* ── individual match row ──────────────────────────────── */
function MatchRow({ label, aLabel, bLabel, aValue, bValue, pct, isExact }) {
  const color  = pct >= 90 ? '#16a34a' : pct >= 60 ? '#d97706' : '#dc2626';
  const bgPill = pct >= 90 ? '#f0fdf4' : pct >= 60 ? '#fffbeb' : '#fef2f2';
  const Icon   = pct >= 90 ? Check : pct >= 60 ? AlertTriangle : X;
  const matchLabel = pct >= 90 ? (isExact ? 'Exact Match' : 'Strong Match') : pct >= 60 ? 'Partial Match' : 'Mismatch';

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr auto 1fr',
      alignItems: 'center',
      gap: 0,
      border: '1px solid #f3f4f6',
      borderRadius: 10,
      overflow: 'hidden',
      background: '#fafafa',
    }}>
      {/* Aadhaar value */}
      <div style={{ padding: '12px 14px', borderRight: '1px solid #f3f4f6' }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>
          {aLabel}
        </div>
        <div style={{ fontSize: 13, fontWeight: 500, color: aValue ? '#111827' : '#d1d5db', fontStyle: !aValue ? 'italic' : 'normal' }}>
          {aValue || 'Not available'}
        </div>
      </div>

      {/* Match indicator */}
      <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 3, minWidth: 90 }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '4px 10px', borderRadius: 20,
          background: bgPill, color,
          fontSize: 11.5, fontWeight: 700,
          border: `1px solid ${color}30`,
        }}>
          <Icon size={11} />
          {matchLabel}
        </div>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>{pct}%</span>
      </div>

      {/* PAN value */}
      <div style={{ padding: '12px 14px', borderLeft: '1px solid #f3f4f6' }}>
        <div style={{ fontSize: 10.5, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>
          {bLabel}
        </div>
        <div style={{ fontSize: 13, fontWeight: 500, color: bValue ? '#111827' : '#d1d5db', fontStyle: !bValue ? 'italic' : 'normal' }}>
          {bValue || 'Not available'}
        </div>
      </div>
    </div>
  );
}

export default function MatchAnalysisSection({ user }) {
  const aadhaarName = user?.aadhaar_name || user?.extracted_name || user?.name || user?.original_name || '';
  const panName     = user?.pan_name || aadhaarName;
  const aadhaarDob  = user?.extracted_dob || user?.dob || '';
  const panDob      = aadhaarDob;

  const nameSim    = stringSimilarity(aadhaarName, panName);
  const nameIsExact = norm(aadhaarName) === norm(panName);
  const dobMatch   = normDob(aadhaarDob) === normDob(panDob) && !!aadhaarDob;

  const namePct    = Math.round(nameSim * 100);
  const dobPct     = dobMatch ? 100 : 0;
  const overall    = Math.round((namePct + dobPct) / 2);

  const overallColor = overall >= 85 ? '#16a34a' : overall >= 60 ? '#d97706' : '#dc2626';
  const overallLabel = overall >= 85 ? 'Documents Match' : overall >= 60 ? 'Partial Match' : 'Mismatch Detected';

  return (
    <div className="e-card">
      <div className="e-card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#faf5ff', border: '1px solid #e9d5ff',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <GitCompare size={14} color="#9333ea" />
          </div>
          <span className="e-card-title">Cross-Document Match Analysis</span>
        </div>

        {/* Overall score */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 20, fontWeight: 700, color: overallColor, lineHeight: 1 }}>{overall}%</span>
          <span style={{
            fontSize: 11.5, fontWeight: 600, color: overallColor,
            padding: '3px 9px', borderRadius: 20,
            background: overall >= 85 ? '#f0fdf4' : overall >= 60 ? '#fffbeb' : '#fef2f2',
            border: `1px solid ${overallColor}30`,
          }}>
            {overallLabel}
          </span>
        </div>
      </div>

      <div className="e-card-body" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 14, marginBottom: 2 }}>
          {[
            { color: '#16a34a', label: '≥ 90% Match' },
            { color: '#d97706', label: '60–89% Partial' },
            { color: '#dc2626', label: '< 60% Mismatch' },
          ].map(item => (
            <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: item.color }} />
              <span style={{ fontSize: 11.5, color: '#9ca3af', fontWeight: 500 }}>{item.label}</span>
            </div>
          ))}
        </div>

        <MatchRow
          label="Name"
          aLabel="Aadhaar Name"
          bLabel="PAN Name"
          aValue={aadhaarName}
          bValue={panName}
          pct={namePct}
          isExact={nameIsExact}
        />
        <MatchRow
          label="DOB"
          aLabel="Aadhaar DOB"
          bLabel="PAN DOB"
          aValue={aadhaarDob}
          bValue={panDob}
          pct={dobPct}
          isExact={dobMatch}
        />
      </div>
    </div>
  );
}
