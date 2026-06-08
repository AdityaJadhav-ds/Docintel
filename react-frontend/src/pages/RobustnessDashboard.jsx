import React, { useState } from 'react';
import {
  Shield, UploadCloud, Play, AlertTriangle,
  CheckCircle2, XCircle, BarChart2, Zap,
  RefreshCw, Download, ChevronDown, ChevronUp,
  Loader2, Activity, Target, Layers
} from 'lucide-react';
import { apiRunRobustness } from '../api/api';

// ── Primitives ────────────────────────────────────────────────────────────────

const Card = ({ title, icon: Icon, children, color = '#64748B' }) => (
  <div style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
    <div style={{ background: '#F8FAFC', borderBottom: '1px solid #E2E8F0', padding: '11px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
      <Icon size={15} color={color} />
      <span style={{ fontSize: 12, fontWeight: 700, color: '#334155', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{title}</span>
    </div>
    <div style={{ padding: 16 }}>{children}</div>
  </div>
);

const ScorePill = ({ score, size = 'md' }) => {
  const color = score >= 90 ? '#15803D' : score >= 75 ? '#1D4ED8' : score >= 55 ? '#D97706' : '#DC2626';
  const bg    = score >= 90 ? '#F0FDF4' : score >= 75 ? '#EFF6FF' : score >= 55 ? '#FFFBEB' : '#FEF2F2';
  const fs    = size === 'lg' ? 32 : 18;
  return (
    <div style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
                  background: bg, border: `2px solid ${color}`, borderRadius: 12,
                  padding: size === 'lg' ? '16px 24px' : '8px 14px' }}>
      <div style={{ fontSize: fs, fontWeight: 800, color }}>{score}</div>
      <div style={{ fontSize: 10, fontWeight: 600, color, textTransform: 'uppercase' }}>/ 100</div>
    </div>
  );
};

const Bar = ({ value, max = 100, color = '#2563EB' }) => (
  <div style={{ flex: 1, background: '#F1F5F9', borderRadius: 4, height: 8, overflow: 'hidden' }}>
    <div style={{ width: `${(value / max) * 100}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.5s' }} />
  </div>
);

const gradeColor = (g) => ({
  excellent: '#15803D', good: '#1D4ED8', fair: '#D97706', poor: '#DC2626'
}[g] || '#64748B');

const FIELD_LABELS = {
  percentage: 'Percentage', candidate_name: 'Candidate Name',
  cgpa: 'CGPA', result: 'Result', grade_class: 'Grade/Class',
};

const TRANSFORM_LABELS = {
  gaussian_blur: 'Gaussian Blur', motion_blur: 'Motion Blur',
  low_brightness: 'Low Light', high_brightness: 'Overexposed',
  perspective_skew: 'Perspective Skew', whatsapp_compress: 'WhatsApp',
  jpeg_artifacts: 'JPEG Artifacts', gaussian_noise: 'Noise',
  rotation: 'Rotation', watermark: 'Watermark',
  partial_crop: 'Partial Crop', screenshot_sim: 'Screenshot',
  shadow_overlay: 'Shadow', low_dpi: 'Low DPI',
};

// ── Ground Truth Input ────────────────────────────────────────────────────────

function GroundTruthForm({ value, onChange }) {
  const fields = ['percentage', 'candidate_name', 'cgpa', 'result'];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {fields.map(f => (
        <div key={f} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <label style={{ fontSize: 11, fontWeight: 600, color: '#475569' }}>{FIELD_LABELS[f] || f}</label>
          <input
            type="text"
            placeholder={f === 'percentage' ? '75.17' : f === 'candidate_name' ? 'Rahul Sharma' : ''}
            value={value[f] || ''}
            onChange={e => onChange({ ...value, [f]: e.target.value || undefined })}
            style={{
              padding: '8px 10px', borderRadius: 8, border: '1px solid #E2E8F0',
              fontSize: 12, color: '#0F172A', background: '#F8FAFC', outline: 'none',
            }}
          />
        </div>
      ))}
    </div>
  );
}

// ── Score Overview ────────────────────────────────────────────────────────────

function ScoreOverview({ score }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: 20, alignItems: 'center' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
        <ScorePill score={score.overall} size="lg" />
        <div style={{ fontSize: 13, fontWeight: 700, color: gradeColor(score.grade), textTransform: 'uppercase' }}>
          {score.grade}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[
          ['Success Rate',   Math.round(score.success_rate  * 100)],
          ['Recovery Rate',  Math.round(score.recovery_rate * 100)],
          ['Avg Retries',    Math.round(score.avg_retries * 10)],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 90, fontSize: 11, color: '#64748B', fontWeight: 600 }}>{label}</div>
            <Bar value={val} />
            <div style={{ width: 34, fontSize: 12, fontWeight: 700, color: '#0F172A', textAlign: 'right' }}>{val}%</div>
          </div>
        ))}
        <div style={{ fontSize: 11, color: '#64748B', marginTop: 4 }}>
          Variants: <b>{score.total_variants}</b>
        </div>
      </div>
    </div>
  );
}

// ── Field Accuracy Chart ──────────────────────────────────────────────────────

function FieldAccuracyChart({ fieldScores }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {Object.entries(fieldScores).map(([field, score]) => {
        const color = score >= 90 ? '#16A34A' : score >= 70 ? '#2563EB' : score >= 50 ? '#D97706' : '#DC2626';
        return (
          <div key={field} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 120, fontSize: 12, color: '#334155', fontWeight: 500 }}>
              {FIELD_LABELS[field] || field}
            </div>
            <Bar value={score} color={color} />
            <ScorePill score={score} />
          </div>
        );
      })}
    </div>
  );
}

// ── Transform Accuracy Chart ──────────────────────────────────────────────────

function TransformChart({ transformScores }) {
  const sorted = Object.entries(transformScores).sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {sorted.map(([t, score]) => {
        const color = score >= 85 ? '#16A34A' : score >= 65 ? '#2563EB' : score >= 45 ? '#D97706' : '#DC2626';
        return (
          <div key={t} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 130, fontSize: 11, color: '#334155', fontWeight: 500 }}>
              {TRANSFORM_LABELS[t] || t}
            </div>
            <Bar value={score} color={color} />
            <div style={{ width: 34, fontSize: 12, fontWeight: 700, color, textAlign: 'right' }}>{score}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── Failure Clusters ──────────────────────────────────────────────────────────

function ClusterList({ clusters }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {clusters.slice(0, 8).map(c => (
        <div key={c.cluster_id} style={{
          padding: '10px 14px', borderRadius: 8,
          background: '#FFF1F2', border: '1px solid #FECACA',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <span style={{ fontSize: 10, fontWeight: 700, color: '#9F1239', marginRight: 8, fontFamily: 'monospace' }}>
                {c.cluster_id}
              </span>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#991B1B' }}>{c.description}</span>
            </div>
            <span style={{ fontSize: 11, fontWeight: 700, color: '#7F1D1D',
              background: '#FEE2E2', padding: '1px 7px', borderRadius: 4 }}>
              {c.count}×
            </span>
          </div>
        </div>
      ))}
      {clusters.length === 0 && (
        <div style={{ color: '#64748B', fontSize: 12, textAlign: 'center', padding: 16 }}>
          No significant failure clusters detected ✅
        </div>
      )}
    </div>
  );
}

// ── Region Heatmap ────────────────────────────────────────────────────────────

function RegionHeatmap({ heatmap }) {
  const regions = ['header_zone', 'candidate_zone', 'summary_zone', 'unknown_zone'];
  const max = Math.max(...Object.values(heatmap), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {regions.map(r => {
        const count = heatmap[r] || 0;
        const pct   = count / max;
        const color = pct > 0.7 ? '#DC2626' : pct > 0.4 ? '#D97706' : '#16A34A';
        return (
          <div key={r} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 120, fontSize: 12, color: '#334155', fontWeight: 500 }}>
              {r.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}
            </div>
            <Bar value={count} max={max} color={color} />
            <div style={{ width: 30, fontSize: 12, fontWeight: 700, color }}>{count}</div>
          </div>
        );
      })}
    </div>
  );
}

// ── Recommendations Panel ─────────────────────────────────────────────────────

function Recommendations({ recs }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {recs.map((r, i) => (
        <div key={i} style={{ fontSize: 12, color: '#334155', lineHeight: 1.6, padding: '8px 12px',
          background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: 8 }}>
          {r}
        </div>
      ))}
    </div>
  );
}

// ── Main Component ────────────────────────────────────────────────────────────

export default function RobustnessDashboard() {
  const [file,        setFile]        = useState(null);
  const [gt,          setGt]          = useState({});
  const [maxVariants, setMaxVariants] = useState(40);
  const [loading,     setLoading]     = useState(false);
  const [report,      setReport]      = useState(null);
  const [error,       setError]       = useState(null);

  const handleRun = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    setReport(null);
    try {
      const data = await apiRunRobustness(file, gt, { maxVariants });
      setReport(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), {
      href: url, download: `robustness_${report.report_id}.json`,
    });
    a.click();
  };

  const score = report?.robustness_score;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20, padding: 24 }}>

      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: '#0F172A', margin: 0 }}>
            🛡 Robustness Testing Dashboard
          </h1>
          <p style={{ color: '#64748B', fontSize: 13, margin: '4px 0 0' }}>
            Adversarial stress testing — 14 degradation types, up to 100 variants
          </p>
        </div>
        {report && (
          <button onClick={downloadReport} style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: '#FFFFFF', border: '1px solid #E2E8F0',
            padding: '8px 14px', borderRadius: 8, fontSize: 12, fontWeight: 600, color: '#475569', cursor: 'pointer',
          }}>
            <Download size={14} /> Export Report
          </button>
        )}
      </div>

      {/* Config + Score Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: 20, alignItems: 'start' }}>

        {/* Config panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Test Configuration" icon={Target}>
            {/* File upload */}
            <div
              onClick={() => document.getElementById('rb-file-input').click()}
              style={{
                border: `2px dashed ${file ? '#2563EB' : '#CBD5E1'}`,
                borderRadius: 10, padding: '16px', textAlign: 'center',
                cursor: 'pointer', background: file ? '#EFF6FF' : '#F8FAFC', marginBottom: 14,
              }}
            >
              <input
                id="rb-file-input" type="file" hidden
                accept="image/jpeg,image/png,image/webp,image/bmp"
                onChange={e => e.target.files?.[0] && setFile(e.target.files[0])}
              />
              <UploadCloud size={24} color={file ? '#2563EB' : '#94A3B8'} style={{ margin: '0 auto 8px' }} />
              <div style={{ fontSize: 12, fontWeight: 600, color: file ? '#1D4ED8' : '#64748B' }}>
                {file ? file.name : 'Upload Clean Reference Document'}
              </div>
            </div>

            {/* Variant count */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#475569', marginBottom: 5 }}>
                Max Variants: {maxVariants}
              </div>
              <input
                type="range" min="10" max="100" step="10"
                value={maxVariants}
                onChange={e => setMaxVariants(Number(e.target.value))}
                style={{ width: '100%' }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#94A3B8' }}>
                <span>10 (fast)</span><span>100 (thorough)</span>
              </div>
            </div>

            {/* Run button */}
            <button
              onClick={handleRun}
              disabled={!file || loading}
              style={{
                width: '100%', padding: '12px', borderRadius: 10, border: 'none',
                background: !file || loading ? '#E2E8F0' : 'linear-gradient(135deg,#1E3A8A,#2563EB)',
                color: !file || loading ? '#94A3B8' : '#FFFFFF',
                fontSize: 13, fontWeight: 700, cursor: !file || loading ? 'not-allowed' : 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              {loading ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={16} />}
              {loading ? 'Running Benchmark...' : 'Run Adversarial Test'}
            </button>

            {error && (
              <div style={{ marginTop: 10, padding: '8px 12px', background: '#FEF2F2',
                border: '1px solid #FECACA', borderRadius: 8, fontSize: 11, color: '#DC2626' }}>
                {error}
              </div>
            )}
          </Card>

          <Card title="Ground Truth (Optional)" icon={CheckCircle2}>
            <div style={{ fontSize: 11, color: '#64748B', marginBottom: 10 }}>
              Enter known values to measure field accuracy. Leave blank to skip per-field scoring.
            </div>
            <GroundTruthForm value={gt} onChange={setGt} />
          </Card>
        </div>

        {/* Results panel */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: 48, color: '#64748B' }}>
              <Activity size={32} style={{ margin: '0 auto 12px', opacity: 0.5, animation: 'pulse 1.5s infinite' }} />
              <p style={{ fontWeight: 600 }}>Running {maxVariants} adversarial variants...</p>
              <p style={{ fontSize: 12 }}>This may take 2–8 minutes depending on image complexity.</p>
            </div>
          )}

          {!loading && !report && (
            <div style={{ textAlign: 'center', padding: 48, color: '#94A3B8', background: '#F8FAFC',
              borderRadius: 12, border: '1px dashed #E2E8F0' }}>
              <Shield size={40} style={{ margin: '0 auto 16px', opacity: 0.4 }} />
              <p style={{ fontWeight: 600 }}>Upload a clean reference document and run the test</p>
            </div>
          )}

          {score && (
            <>
              <Card title="Overall Robustness Score" icon={Shield} color={gradeColor(score.grade)}>
                <ScoreOverview score={score} />
                <div style={{ marginTop: 14, padding: '10px 14px', background: '#F8FAFC',
                  border: '1px solid #E2E8F0', borderRadius: 8, fontSize: 12, color: '#475569' }}>
                  {score.weakness_summary}
                </div>
              </Card>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <Card title="Field Accuracy" icon={BarChart2}>
                  <FieldAccuracyChart fieldScores={score.field_scores} />
                </Card>
                <Card title="By Degradation Type" icon={Layers}>
                  <TransformChart transformScores={score.transform_scores} />
                </Card>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                <Card title="Failure Clusters" icon={XCircle} color="#DC2626">
                  <ClusterList clusters={report.failure_clusters || []} />
                </Card>
                <Card title="Region Failure Heatmap" icon={Zap} color="#D97706">
                  <RegionHeatmap heatmap={report.region_heatmap || {}} />
                </Card>
              </div>

              <Card title="Auto-Tuning Recommendations" icon={RefreshCw} color="#7C3AED">
                <Recommendations recs={report.recommendations || []} />
              </Card>
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
      `}</style>
    </div>
  );
}
