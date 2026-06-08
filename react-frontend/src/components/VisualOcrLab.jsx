import React, { useState } from 'react';
import {
  Layers, Target, Image as ImageIcon,
  CheckCircle2, XCircle, AlertCircle, Clock,
  Code, Download, Activity, RefreshCw,
  BarChart2, ChevronDown, ChevronUp
} from 'lucide-react';

// ── Shared primitives ────────────────────────────────────────────────────────

const Card = ({ title, icon: Icon, children, accent }) => (
  <div style={{
    background: '#FFFFFF', border: `1px solid ${accent ? '#BFDBFE' : '#E2E8F0'}`,
    borderRadius: 12, overflow: 'hidden',
    boxShadow: accent ? '0 1px 6px rgba(37,99,235,0.08)' : '0 1px 3px rgba(0,0,0,0.03)',
  }}>
    <div style={{
      background: accent ? '#EFF6FF' : '#F8FAFC',
      borderBottom: `1px solid ${accent ? '#BFDBFE' : '#E2E8F0'}`,
      padding: '11px 16px', display: 'flex', alignItems: 'center', gap: 8,
    }}>
      <Icon size={15} color={accent ? '#2563EB' : '#64748B'} />
      <span style={{
        fontSize: 12, fontWeight: 700,
        color: accent ? '#1D4ED8' : '#334155',
        textTransform: 'uppercase', letterSpacing: '0.05em',
      }}>{title}</span>
    </div>
    <div style={{ padding: 14 }}>{children}</div>
  </div>
);

const Tag = ({ children, color = '#2563EB', bg = '#EFF6FF' }) => (
  <span style={{
    display: 'inline-flex', alignItems: 'center',
    padding: '2px 8px', borderRadius: 6, fontSize: 11, fontWeight: 700,
    color, background: bg,
  }}>{children}</span>
);

const DebugImage = ({ b64, title, height = 180 }) => {
  if (!b64) {
    return (
      <div style={{
        background: '#F1F5F9', border: '1px dashed #CBD5E1', borderRadius: 8,
        height: Math.min(height, 120),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#94A3B8', fontSize: 11, fontWeight: 600,
      }}>
        {title ? `${title} — Not Available` : 'Not Available'}
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
      {title && <div style={{ fontSize: 11, fontWeight: 600, color: '#64748B' }}>{title}</div>}
      <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8, overflow: 'hidden' }}>
        <img
          src={`data:image/jpeg;base64,${b64}`}
          alt={title || 'debug'}
          style={{ maxWidth: '100%', maxHeight: height, display: 'block', objectFit: 'contain', margin: '0 auto' }}
        />
      </div>
    </div>
  );
};

// ── Pipeline Timeline ─────────────────────────────────────────────────────────

function PipelineTimeline({ v2, meta }) {
  const stages = [
    { label: 'Document Restoration',  ok: true },
    { label: `Layout: ${v2.layout_class || 'unknown'}`, ok: !!v2.layout_class },
    { label: `Zone Segmentation (${(v2.zones_detected || []).length} zones)`, ok: (v2.zones_detected || []).length > 0 },
    { label: `Table Masking${v2.table_detected ? ' ✓' : ' — Not found'}`,     ok: true },
    { label: `Summary Anchors${v2.summary_anchors_found ? ' ✓' : ' — None'}`, ok: v2.summary_anchors_found },
    { label: `Adaptive Extraction${v2.adaptive_engine ? '' : ' (v1 fallback)'}`, ok: v2.adaptive_engine },
    { label: `Validation: ${meta.status}`,   ok: meta.status !== 'failed' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
      {stages.map((s, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {s.ok
            ? <CheckCircle2 size={15} color="#16A34A" />
            : <AlertCircle  size={15} color="#F59E0B" />
          }
          <span style={{ fontSize: 12, color: s.ok ? '#0F172A' : '#92400E', fontWeight: s.ok ? 500 : 600 }}>
            {s.label}
          </span>
        </div>
      ))}
      {meta.warnings?.length > 0 && (
        <div style={{ marginTop: 8, paddingTop: 10, borderTop: '1px solid #E2E8F0' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: '#DC2626', marginBottom: 5 }}>WARNINGS</div>
          {meta.warnings.map((w, i) => (
            <div key={i} style={{ fontSize: 11, color: '#991B1B', marginBottom: 3 }}>⚠ {w}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Failure Inspector ─────────────────────────────────────────────────────────

function FailureInspector({ failures }) {
  if (!failures || Object.keys(failures).length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(failures).map(([field, reason]) => (
        <div key={field} style={{
          background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 8, padding: '8px 12px',
        }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 3 }}>
            <XCircle size={14} color="#DC2626" />
            <span style={{ fontSize: 12, fontWeight: 700, color: '#991B1B', textTransform: 'uppercase' }}>{field}</span>
          </div>
          <div style={{ fontSize: 11, color: '#B91C1C', lineHeight: 1.5 }}>{reason}</div>
        </div>
      ))}
    </div>
  );
}

// ── Field ROI Detail ──────────────────────────────────────────────────────────

function FieldROIDetail({ fieldName, ar, image, anchorText, ocrText }) {
  const [expanded, setExpanded] = useState(false);
  const attempts = ar?.attempts || [];
  const found = ar?.found;

  return (
    <div style={{
      border: `1px solid ${found ? '#D1FAE5' : '#FEE2E2'}`,
      borderRadius: 10, overflow: 'hidden',
    }}>
      {/* Header row */}
      <div
        onClick={() => setExpanded(e => !e)}
        style={{
          display: 'grid', gridTemplateColumns: '100px 120px 1fr auto',
          gap: 12, alignItems: 'center', padding: '10px 14px',
          background: found ? '#F0FDF4' : '#FFF1F2', cursor: 'pointer',
        }}
      >
        <div style={{ fontSize: 12, fontWeight: 700, color: '#334155', textTransform: 'uppercase' }}>
          {fieldName}
        </div>
        {found
          ? <Tag color="#15803D" bg="#DCFCE7">✓ {ar.strategy_used?.split(':')[0] || 'found'}</Tag>
          : <Tag color="#DC2626" bg="#FEE2E2">✗ not found</Tag>
        }
        <div style={{ fontSize: 12, color: '#475569' }}>
          {ar?.value
            ? <span style={{ fontWeight: 700, color: '#0F172A' }}>{ar.value}</span>
            : <span style={{ color: '#94A3B8' }}>—</span>
          }
          {ar?.recovered && <Tag color="#7C3AED" bg="#F5F3FF" style={{ marginLeft: 6 }}>Recovered</Tag>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, color: '#64748B', fontSize: 11 }}>
          {attempts.length} attempt{attempts.length !== 1 ? 's' : ''}
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ padding: 14, borderTop: '1px solid #E2E8F0', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {/* ROI image + text */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <DebugImage b64={image} title="Preprocessed ROI" height={140} />
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 10, color: '#64748B', marginBottom: 3 }}>Spatial Anchor</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#0F172A' }}>
                  {anchorText || <span style={{ color: '#94A3B8' }}>None</span>}
                </div>
              </div>
              <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ fontSize: 10, color: '#64748B', marginBottom: 3 }}>OCR Zone Text</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: '#0F172A', wordBreak: 'break-all' }}>
                  {ocrText || <span style={{ color: '#94A3B8' }}>None</span>}
                </div>
              </div>
            </div>
          </div>

          {/* Attempt log */}
          {attempts.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', marginBottom: 8, textTransform: 'uppercase' }}>
                Retry Attempts
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {attempts.map((att, i) => (
                  <div key={i} style={{
                    display: 'grid', gridTemplateColumns: '24px 140px 80px 1fr',
                    gap: 10, alignItems: 'center',
                    padding: '6px 10px', borderRadius: 6,
                    background: att.valid ? '#F0FDF4' : '#F8FAFC',
                    border: `1px solid ${att.valid ? '#BBF7D0' : '#E2E8F0'}`,
                  }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: '#64748B' }}>#{att.attempt}</div>
                    <div style={{ fontSize: 11, color: '#475569', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {att.strategy}
                    </div>
                    <Tag
                      color={att.valid ? '#15803D' : '#94A3B8'}
                      bg={att.valid ? '#DCFCE7' : '#F1F5F9'}
                    >
                      {att.valid ? '✓ valid' : '✗ invalid'}
                    </Tag>
                    <div style={{ fontSize: 11, color: '#0F172A', fontWeight: att.valid ? 600 : 400 }}>
                      {att.text || att.failure_reason || '—'}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Adaptive Metrics Panel ────────────────────────────────────────────────────

function AdaptiveMetrics({ metrics }) {
  if (!metrics || Object.keys(metrics).length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {Object.entries(metrics).map(([field, stats]) => (
        <div key={field} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#334155', textTransform: 'uppercase' }}>{field}</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 4 }}>
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '5px 8px', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: stats.success_rate >= 0.7 ? '#16A34A' : '#F59E0B' }}>
                {Math.round((stats.success_rate || 0) * 100)}%
              </div>
              <div style={{ fontSize: 9, color: '#64748B' }}>Success</div>
            </div>
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '5px 8px', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0F172A' }}>{stats.avg_attempts || 0}</div>
              <div style={{ fontSize: 9, color: '#64748B' }}>Avg Attempts</div>
            </div>
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '5px 8px', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#7C3AED' }}>
                {Math.round((stats.recovery_rate || 0) * 100)}%
              </div>
              <div style={{ fontSize: 9, color: '#64748B' }}>Recovered</div>
            </div>
            <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 6, padding: '5px 8px', textAlign: 'center' }}>
              <div style={{ fontSize: 16, fontWeight: 700, color: '#0891B2' }}>
                {Math.round((stats.avg_confidence || 0) * 100)}%
              </div>
              <div style={{ fontSize: 9, color: '#64748B' }}>Avg Conf</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function VisualOcrLab({ result }) {
  if (!result) return null;

  const meta     = result._meta || {};
  const v2       = meta.layout_v2_meta || {};
  const images   = v2.debug_images || {};
  const texts    = v2.zone_texts || {};
  const anchors  = v2.anchor_fields || {};
  const adpRes   = v2.adaptive_results || {};
  const failures = v2.failure_reasons || {};
  const adpMet   = v2.adaptive_metrics || {};
  const isV2     = meta.extraction_engine === 'layout_v2';

  const exportDebug = () => {
    const blob = new Blob([JSON.stringify({ result, v2_meta: v2 }, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), {
      href: url,
      download: `ocr_debug_${(meta.document_id || '').substring(0, 8)}.json`,
    });
    a.click();
  };

  if (!isV2) {
    return (
      <div style={{ padding: 28, textAlign: 'center', color: '#64748B', background: '#F8FAFC', borderRadius: 12, border: '1px dashed #CBD5E1' }}>
        <AlertCircle size={28} style={{ margin: '0 auto 12px', opacity: 0.5 }} />
        <p style={{ fontWeight: 600, marginBottom: 6 }}>Visual Lab requires Layout Intelligence v2</p>
        <p style={{ fontSize: 12 }}>This result used the v1 fallback engine — v2 found no target fields.</p>
      </div>
    );
  }

  const fields = ['percentage', 'cgpa', 'result', 'candidate'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: '#0F172A' }}>Visual OCR Intelligence Lab</span>
          <Tag>v2 ENGINE</Tag>
          <Tag color="#64748B" bg="#F1F5F9">
            <Clock size={12} style={{ marginRight: 4 }} />
            {v2.elapsed_ms}ms
          </Tag>
          {v2.adaptive_engine && <Tag color="#7C3AED" bg="#F5F3FF">ADAPTIVE</Tag>}
        </div>
        <button onClick={exportDebug} style={{
          display: 'flex', alignItems: 'center', gap: 6,
          background: '#FFFFFF', border: '1px solid #E2E8F0', padding: '6px 12px',
          borderRadius: 6, fontSize: 12, fontWeight: 600, color: '#475569', cursor: 'pointer',
        }}>
          <Download size={13} /> Export Debug JSON
        </button>
      </div>

      {/* 2-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 20, alignItems: 'start' }}>

        {/* LEFT: Timeline + Classification + Failures + Metrics */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          <Card title="Pipeline Timeline" icon={Activity}>
            <PipelineTimeline v2={v2} meta={meta} />
          </Card>

          <Card title="Layout Classification" icon={Layers}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
              {[
                ['Variant', v2.layout_class],
                ['Zones Active', (v2.zones_detected || []).length],
                ['Table Mask', v2.table_detected ? 'Applied' : 'Not Found'],
                ['Anchors', v2.summary_anchors_found ? 'Detected' : 'None'],
                ['Engine', v2.adaptive_engine ? 'Adaptive v2' : 'Single-pass v1'],
              ].map(([k, v]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span style={{ color: '#64748B' }}>{k}</span>
                  <span style={{ fontWeight: 600, color: '#0F172A' }}>{String(v)}</span>
                </div>
              ))}
            </div>
          </Card>

          {Object.keys(failures).length > 0 && (
            <Card title="Failure Inspector" icon={XCircle}>
              <FailureInspector failures={failures} />
            </Card>
          )}

          {Object.keys(adpMet).length > 0 && (
            <Card title="Adaptive Metrics" icon={BarChart2}>
              <AdaptiveMetrics metrics={adpMet} />
            </Card>
          )}

        </div>

        {/* RIGHT: Zone overlay + Field ROI details */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

          <Card title="1. Zone Segmentation Overlay" icon={Target} accent>
            <DebugImage b64={images.zones_annotated || images.layout_zones} height={280} />
            <div style={{ display: 'flex', gap: 10, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <span style={{ fontSize: 10, color: '#64748B', fontWeight: 600 }}>LEGEND:</span>
              {[
                ['Header', '#C8B400'], ['Candidate', '#00DC32'],
                ['Subjects (masked)', '#3232C8'], ['Summary', '#0080FF'], ['Noise', '#960096']
              ].map(([label, color]) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{ width: 12, height: 3, background: color, borderRadius: 2 }} />
                  <span style={{ fontSize: 10, color: '#475569' }}>{label}</span>
                </div>
              ))}
            </div>
          </Card>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
            <Card title="2. Summary Zone Crop" icon={ImageIcon}>
              <DebugImage b64={images.zone_summary} height={150} />
            </Card>
            <Card title="3. Candidate Zone Crop" icon={ImageIcon}>
              <DebugImage b64={images.zone_candidate} height={150} />
            </Card>
          </div>

          <Card title="4. Field ROI Diagnostics (click to expand)" icon={Code}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {fields.map(f => (
                <FieldROIDetail
                  key={f}
                  fieldName={f}
                  ar={adpRes[f]}
                  image={images[`ocr_${f}`] || images[`roi_${f}`]}
                  anchorText={anchors[f] || anchors[f === 'candidate' ? 'candidate_name' : f]}
                  ocrText={texts[f]}
                />
              ))}
            </div>
          </Card>

          <Card title="5. OCR Engine Summary" icon={RefreshCw}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {(meta.ocr_engines || []).map(e => (
                <Tag key={e} color="#0891B2" bg="#ECFEFF">{e}</Tag>
              ))}
              {(meta.ocr_engines || []).length === 0 && (
                <span style={{ fontSize: 12, color: '#94A3B8' }}>No engines recorded</span>
              )}
            </div>
          </Card>

        </div>
      </div>
    </div>
  );
}
