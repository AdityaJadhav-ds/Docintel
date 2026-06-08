/* OCRInsightsSection — collapsible with clean light styling */

import { useState } from 'react';
import { ChevronDown, ChevronUp, Cpu, Activity } from 'lucide-react';

export default function OCRInsightsSection({ user, ocrDebug }) {
  const [open, setOpen] = useState(false);

  const conf    = user?.confidence || 0;
  const raw     = ocrDebug?.ocr?.raw_merged_text || '';
  const engine  = ocrDebug?.debug?.engines_used?.join(', ') || 'EasyOCR + Tesseract';
  const variant = ocrDebug?.debug?.preprocessing_variants?.join(', ') || '—';

  const confColor = conf >= 85 ? '#16a34a' : conf >= 60 ? '#d97706' : '#dc2626';

  return (
    <div className="e-card">
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', background: 'none', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 18px', font: 'inherit',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{
            width: 28, height: 28, borderRadius: 7,
            background: '#fffbeb', border: '1px solid #fde68a',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Cpu size={14} color="#d97706" />
          </div>
          <span className="e-card-title">OCR Insights</span>
          <span style={{ fontSize: 11.5, color: '#9ca3af', fontWeight: 500 }}>
            · {conf > 0 ? `${conf}% confidence` : 'No data yet'}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: confColor }}>{conf}%</span>
          {open ? <ChevronUp size={16} color="#9ca3af" /> : <ChevronDown size={16} color="#9ca3af" />}
        </div>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid #f3f4f6' }}>
          {/* Stats row */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', borderBottom: '1px solid #f3f4f6' }}>
            {[
              { label: 'OCR Engine',      value: engine },
              { label: 'Preprocessing',   value: variant },
              { label: 'Characters',      value: raw.length || '—' },
            ].map((s, i) => (
              <div key={s.label} style={{
                padding: '12px 16px',
                borderRight: i < 2 ? '1px solid #f3f4f6' : 'none',
              }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 4 }}>
                  {s.label}
                </div>
                <div style={{ fontSize: 13, fontWeight: 500, color: '#374151', wordBreak: 'break-all' }}>
                  {String(s.value)}
                </div>
              </div>
            ))}
          </div>

          {/* Raw OCR text */}
          <div style={{ padding: '14px 18px' }}>
            {raw ? (
              <>
                <div style={{ fontSize: 11, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 8 }}>
                  Raw OCR Output
                </div>
                <pre style={{
                  margin: 0, padding: '12px 14px',
                  background: '#f9fafb', border: '1px solid #f3f4f6',
                  borderRadius: 8, fontSize: 12, lineHeight: 1.7,
                  color: '#4b5563', fontFamily: "'SF Mono', 'Roboto Mono', Consolas, monospace",
                  maxHeight: 140, overflow: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                }}>
                  {raw.slice(0, 800)}{raw.length > 800 ? '…' : ''}
                </pre>
              </>
            ) : (
              <div style={{
                padding: '16px 0', textAlign: 'center',
                fontSize: 13, color: '#9ca3af', fontStyle: 'italic',
              }}>
                No OCR debug data. Use the OCR Debug tool for detailed pipeline insights.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
