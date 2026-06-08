import { GitCompare, Check, AlertTriangle, X } from 'lucide-react';

function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function normId(s) { return (s || '').replace(/\s/g, '').toUpperCase(); }
function normDob(s) {
  let d = (s || '').trim();
  if (d.length === 10 && (d[4] === '-' || d[4] === '/')) return d.replace(/\//g, '-');
  if (d.length === 10 && (d[2] === '-' || d[2] === '/')) {
    const p = d.replace(/\//g, '-').split('-');
    return `${p[2]}-${p[1]}-${p[0]}`;
  }
  return d;
}

function similarity(a, b) {
  if (!a || !b) return 0;
  const na = norm(a), nb = norm(b);
  if (na === nb) return 1;
  const longer = na.length > nb.length ? na : nb;
  const shorter = na.length > nb.length ? nb : na;
  if (longer.length === 0) return 1;
  let matches = 0;
  for (let i = 0; i < shorter.length; i++) {
    if (longer.includes(shorter[i])) matches++;
  }
  return matches / longer.length;
}

function MatchRow({ label, aValue, bValue, matchFn }) {
  const aClean = aValue || '';
  const bClean = bValue || '';
  const score = matchFn
    ? matchFn(aClean, bClean)
    : norm(aClean) === norm(bClean) ? 1 : similarity(aClean, bClean);

  const pct = Math.round(score * 100);
  const isMatch = pct >= 90;
  const isPartial = pct >= 60 && pct < 90;
  const isMismatch = pct < 60;

  const color = isMatch ? '#10b981' : isPartial ? '#f59e0b' : '#ef4444';
  const bg = isMatch ? 'rgba(16,185,129,0.08)' : isPartial ? 'rgba(245,158,11,0.08)' : 'rgba(239,68,68,0.08)';
  const border = isMatch ? 'rgba(16,185,129,0.2)' : isPartial ? 'rgba(245,158,11,0.2)' : 'rgba(239,68,68,0.2)';

  const Icon = isMatch ? Check : isPartial ? AlertTriangle : X;

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, overflow: 'hidden' }}>
      {/* Label */}
      <div style={{ padding: '8px 14px', borderBottom: '1px solid #1e293b', background: 'rgba(255,255,255,0.02)' }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em' }}>{label}</span>
      </div>

      {/* Values */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto 1fr', gap: 0, alignItems: 'center' }}>
        {/* Aadhaar value */}
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase' }}>Aadhaar</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: aClean ? '#f1f5f9' : '#475569', fontStyle: !aClean ? 'italic' : 'normal' }}>
            {aClean || 'Not available'}
          </div>
        </div>

        {/* Match indicator */}
        <div style={{
          padding: '8px 10px',
          display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            background: bg, border: `1px solid ${border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Icon size={13} color={color} />
          </div>
          <span style={{ fontSize: 11, fontWeight: 700, color }}>{pct}%</span>
        </div>

        {/* PAN value */}
        <div style={{ padding: '12px 14px' }}>
          <div style={{ fontSize: 10, color: '#64748b', fontWeight: 600, marginBottom: 4, textTransform: 'uppercase' }}>PAN</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: bClean ? '#f1f5f9' : '#475569', fontStyle: !bClean ? 'italic' : 'normal' }}>
            {bClean || 'Not available'}
          </div>
        </div>
      </div>

      {/* Match bar */}
      <div style={{ height: 3, background: '#1e293b', borderTop: '1px solid #1e293b' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, transition: 'width 0.8s ease' }} />
      </div>
    </div>
  );
}

export default function MatchAnalysisCard({ user }) {
  const aadhaarName = user?.aadhaar_name || user?.extracted_name || user?.name || user?.original_name || '';
  const panName     = user?.pan_name || user?.extracted_name || user?.name || user?.original_name || '';
  const aadhaarDob  = user?.extracted_dob || user?.dob || '';
  const panDob      = user?.extracted_dob || user?.dob || '';

  // Overall name similarity
  const nameSim = similarity(aadhaarName, panName);
  const dobMatch = normDob(aadhaarDob) === normDob(panDob) && aadhaarDob;
  const overallScore = Math.round(((nameSim + (dobMatch ? 1 : 0)) / 2) * 100);

  const overallColor = overallScore >= 85 ? '#10b981' : overallScore >= 60 ? '#f59e0b' : '#ef4444';
  const overallLabel = overallScore >= 85 ? 'Strong Match' : overallScore >= 60 ? 'Partial Match' : 'Mismatch Detected';

  return (
    <div style={{
      background: '#0f172a', border: '1px solid #1e293b', borderRadius: 16, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '16px 20px', borderBottom: '1px solid #1e293b',
        background: 'linear-gradient(135deg, rgba(139,92,246,0.05) 0%, transparent 100%)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: 'rgba(139,92,246,0.15)', border: '1px solid rgba(139,92,246,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <GitCompare size={17} color="#a78bfa" />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>Cross-Document Match Analysis</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>Aadhaar ↔ PAN field comparison</div>
          </div>
        </div>
        {/* Overall score chip */}
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4
        }}>
          <div style={{ fontSize: 22, fontWeight: 800, color: overallColor, lineHeight: 1 }}>{overallScore}%</div>
          <span style={{ fontSize: 11, fontWeight: 700, color: overallColor, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {overallLabel}
          </span>
        </div>
      </div>

      {/* Comparison rows */}
      <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <MatchRow
          label="Full Name"
          aValue={aadhaarName}
          bValue={panName}
        />
        <MatchRow
          label="Date of Birth"
          aValue={aadhaarDob}
          bValue={panDob}
          matchFn={(a, b) => normDob(a) === normDob(b) && a ? 1 : 0}
        />
      </div>

      {/* Legend */}
      <div style={{
        padding: '10px 20px', borderTop: '1px solid #1e293b',
        display: 'flex', gap: 16,
      }}>
        {[
          { color: '#10b981', label: '≥90% Match' },
          { color: '#f59e0b', label: '60–89% Partial' },
          { color: '#ef4444', label: '<60% Mismatch' },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: item.color }} />
            <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
