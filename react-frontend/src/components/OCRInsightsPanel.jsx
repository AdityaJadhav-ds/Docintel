import { useState } from 'react';
import { Brain, ChevronDown, ChevronUp, Cpu, FileSearch, BarChart3 } from 'lucide-react';

function ConfidenceRing({ value, size = 56 }) {
  const pct = Math.round((value || 0) * 100);
  const r = (size / 2) - 6;
  const circ = 2 * Math.PI * r;
  const dash = (pct / 100) * circ;
  const color = pct >= 85 ? '#10b981' : pct >= 60 ? '#f59e0b' : '#ef4444';

  return (
    <div style={{ position: 'relative', width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#1e293b" strokeWidth={5} />
        <circle
          cx={size/2} cy={size/2} r={r} fill="none"
          stroke={color} strokeWidth={5}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.8s ease' }}
        />
      </svg>
      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center',
        justifyContent: 'center', fontSize: 12, fontWeight: 800, color,
      }}>
        {pct}%
      </div>
    </div>
  );
}

function TextBlock({ label, text, maxHeight = 120 }) {
  const [expanded, setExpanded] = useState(false);
  if (!text) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{
        background: '#020617', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 14px',
        fontFamily: "'Roboto Mono', monospace", fontSize: 12, color: '#94a3b8',
        lineHeight: 1.7, maxHeight: expanded ? 'none' : maxHeight, overflow: 'hidden',
        position: 'relative', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      }}>
        {text}
        {!expanded && text.length > 400 && (
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0, height: 40,
            background: 'linear-gradient(transparent, #020617)',
          }} />
        )}
      </div>
      {text.length > 400 && (
        <button onClick={() => setExpanded(e => !e)} style={{
          background: 'none', border: 'none', cursor: 'pointer',
          color: '#818cf8', fontSize: 12, fontWeight: 600, marginTop: 6,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          {expanded ? <><ChevronUp size={13} /> Show less</> : <><ChevronDown size={13} /> Show full text</>}
        </button>
      )}
    </div>
  );
}

export default function OCRInsightsPanel({ user, ocrDebug }) {
  const [open, setOpen] = useState(false);

  const conf = user?.confidence / 100 || ocrDebug?.extraction?.overall_confidence || 0;
  const engine = ocrDebug?.debug?.engines_used?.join(', ') || 'EasyOCR + Tesseract';
  const preprocessing = ocrDebug?.debug?.preprocessing_variants?.join(', ') || '—';
  const rawText = ocrDebug?.ocr?.raw_merged_text || '';
  const variantTexts = ocrDebug?.ocr?.variant_texts || {};

  const stats = [
    { label: 'Engine', value: engine, icon: Cpu },
    { label: 'Preprocessing', value: preprocessing, icon: FileSearch },
    { label: 'Characters', value: ocrDebug?.ocr?.char_count ?? (rawText.length || '—'), icon: BarChart3 },
  ];

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 16, overflow: 'hidden' }}>
      {/* Collapsible Header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '16px 20px',
          background: open ? 'linear-gradient(135deg, rgba(251,191,36,0.05) 0%, transparent 100%)' : 'transparent',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: 'rgba(251,191,36,0.12)', border: '1px solid rgba(251,191,36,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Brain size={17} color="#fbbf24" />
          </div>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9' }}>OCR Intelligence</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>Pipeline details · Raw text · Confidence scores</div>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <ConfidenceRing value={conf} size={44} />
          {open ? <ChevronUp size={18} color="#64748b" /> : <ChevronDown size={18} color="#64748b" />}
        </div>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid #1e293b' }}>
          {/* Stats row */}
          <div style={{
            display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
            borderBottom: '1px solid #1e293b',
          }}>
            {stats.map((s, i) => {
              const Icon = s.icon;
              return (
                <div key={s.label} style={{
                  padding: '14px 16px',
                  borderRight: i < stats.length - 1 ? '1px solid #1e293b' : 'none',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <Icon size={13} color="#64748b" />
                    <span style={{ fontSize: 11, color: '#64748b', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.07em' }}>{s.label}</span>
                  </div>
                  <div style={{ fontSize: 13, fontWeight: 600, color: '#94a3b8', wordBreak: 'break-all' }}>{String(s.value)}</div>
                </div>
              );
            })}
          </div>

          {/* Text sections */}
          <div style={{ padding: '16px 20px' }}>
            {rawText && <TextBlock label="Raw OCR Text (merged)" text={rawText} maxHeight={120} />}
            {Object.entries(variantTexts).map(([variant, text]) => (
              <TextBlock key={variant} label={`Variant: ${variant}`} text={text} maxHeight={80} />
            ))}
            {!rawText && (
              <div style={{ fontSize: 13, color: '#475569', textAlign: 'center', padding: '24px 0', fontStyle: 'italic' }}>
                No OCR debug data available. Run the document through the OCR Debug tool for detailed insights.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
