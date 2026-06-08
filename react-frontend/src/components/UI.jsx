export function StatCard({ icon, label, value, color, bg, sub, pulse }) {
  return (
    <div className="stat-card card-hover" style={{ display: 'flex', alignItems: 'flex-start', gap: 14 }}>
      <div style={{ width: 40, height: 40, borderRadius: 9, background: bg || '#EEF2FF', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, color: color || '#4F46E5' }}>
        {icon}
      </div>
      <div>
        <p style={{ fontSize: '0.72rem', fontWeight: 600, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>{label}</p>
        <div style={{ fontSize: '1.85rem', fontWeight: 800, color: '#0F172A', lineHeight: 1, marginTop: 5 }}>{value ?? '—'}</div>
        {sub && <p style={{ fontSize: '0.75rem', color: '#94A3B8', marginTop: 3 }}>{sub}</p>}
      </div>
    </div>
  );
}

export function Badge({ status }) {
  if (!status) return <span className="badge badge-gray">—</span>;
  const s = status.toLowerCase();
  if (s.includes('approved') || s.includes('verified') || s.includes('matched')) return <span className="badge badge-green">{status}</span>;
  if (s.includes('rejected') || s.includes('invalid') || s.includes('error'))    return <span className="badge badge-red">{status}</span>;
  if (s.includes('review'))     return <span className="badge badge-yellow">{status}</span>;
  if (s.includes('extracted'))  return <span className="badge badge-blue">{status}</span>;
  return <span className="badge badge-gray">{status}</span>;
}

export function Card({ children, className = '' }) {
  return (
    <div className={`card ${className}`} style={{ padding: 24 }}>
      {children}
    </div>
  );
}

export function Spinner() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', padding: '48px 16px' }}>
      <div style={{ width: 32, height: 32, borderRadius: '50%', border: '3px solid #E2E8F0', borderTopColor: '#4F46E5', animation: 'spin 0.7s linear infinite' }} />
    </div>
  );
}
