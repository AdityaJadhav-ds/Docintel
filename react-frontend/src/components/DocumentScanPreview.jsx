/**
 * DocumentScanPreview.jsx
 * =======================
 * Step 1 — Academic Document Scanner Preview Component.
 *
 * Shows:
 *   ORIGINAL IMAGE  →  RESTORED SCAN
 *
 * Lets the user upload any document (photo / PDF / WhatsApp scan) and see
 * the pipeline-restored version side-by-side before OCR runs.
 *
 * Uses: apiRestoreDocument() from api.js
 */

import React, { useState, useRef, useCallback } from 'react';
import { apiRestoreDocument } from '../api/api';
import './DocumentScanPreview.css';

// ── Score badge helper ─────────────────────────────────────────────────────
function ScoreBadge({ label, value, unit = '', invert = false }) {
  const pct   = typeof value === 'number' ? Math.round(value) : 0;
  const color = invert
    ? pct > 60 ? '#ff4d6d' : pct > 30 ? '#ffd166' : '#06d6a0'
    : pct >= 75 ? '#06d6a0' : pct >= 45 ? '#ffd166' : '#ff4d6d';

  return (
    <div className="dsp-score-badge">
      <span className="dsp-score-label">{label}</span>
      <span className="dsp-score-value" style={{ color }}>
        {unit === '°' ? value?.toFixed(1) : pct}{unit || '%'}
      </span>
      <div className="dsp-score-bar">
        <div
          className="dsp-score-fill"
          style={{ width: `${Math.min(100, pct)}%`, background: color }}
        />
      </div>
    </div>
  );
}

// ── Stage chip ─────────────────────────────────────────────────────────────
function StageChip({ label, status }) {
  const statusClass =
    status === 'ok'    ? 'ok'    :
    status === 'error' ? 'error' :
    status === 'skip'  ? 'skip'  : 'ok';
  return (
    <div className={`dsp-chip dsp-chip--${statusClass}`}>
      <span className="dsp-chip-dot" />
      {label}
    </div>
  );
}

// ── Drag-drop upload zone ──────────────────────────────────────────────────
function DropZone({ onFile, disabled }) {
  const inputRef   = useRef(null);
  const [drag, setDrag] = useState(false);

  const handleDrop = useCallback(e => {
    e.preventDefault();
    setDrag(false);
    if (disabled) return;
    const f = e.dataTransfer?.files?.[0];
    if (f) onFile(f);
  }, [onFile, disabled]);

  return (
    <div
      className={`dsp-dropzone ${drag ? 'dsp-dropzone--active' : ''} ${disabled ? 'dsp-dropzone--disabled' : ''}`}
      onDragOver={e => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept="image/*,application/pdf"
        style={{ display: 'none' }}
        onChange={e => { const f = e.target.files?.[0]; if (f) onFile(f); }}
      />
      <div className="dsp-dropzone-icon">📄</div>
      <p className="dsp-dropzone-title">Drop marksheet / certificate here</p>
      <p className="dsp-dropzone-hint">
        JPEG · PNG · WebP · PDF · WhatsApp photo — any quality
      </p>
    </div>
  );
}

// ── Image pane ─────────────────────────────────────────────────────────────
function ImagePane({ title, badge, b64, placeholder }) {
  return (
    <div className="dsp-pane">
      <div className="dsp-pane-header">
        <span className="dsp-pane-title">{title}</span>
        {badge && <span className={`dsp-pane-badge dsp-pane-badge--${badge.toLowerCase().replace(/\s+/g, '-')}`}>{badge}</span>}
      </div>
      <div className="dsp-pane-body">
        {b64 ? (
          <img
            className="dsp-pane-img"
            src={`data:image/jpeg;base64,${b64}`}
            alt={title}
          />
        ) : (
          <div className="dsp-pane-placeholder">
            <span>{placeholder}</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────
export default function DocumentScanPreview() {
  const [file,      setFile]      = useState(null);
  const [loading,   setLoading]   = useState(false);
  const [result,    setResult]    = useState(null);
  const [error,     setError]     = useState('');
  const [aggressive, setAggressive] = useState(false);

  const handleFile = useCallback(f => {
    setFile(f);
    setResult(null);
    setError('');
  }, []);

  const runRestore = useCallback(async () => {
    if (!file) return;
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const data = await apiRestoreDocument(file, aggressive);
      setResult(data);
    } catch (err) {
      setError(err.message || 'Pipeline failed');
    } finally {
      setLoading(false);
    }
  }, [file, aggressive]);

  // Stage metadata → chip list
  const stages = result?.stage_metadata ? [
    { label: 'Boundary Detection',    key: 'boundary' },
    { label: 'Perspective Correction', key: 'perspective' },
    { label: 'Shadow Removal',         key: 'shadow_removal' },
    { label: 'Background Cleanup',     key: 'background_cleanup' },
    { label: 'Super Resolution',       key: 'super_resolution' },
    { label: 'Enhancement',            key: 'enhancement' },
  ].map(s => ({
    label:  s.label,
    status: result.stage_metadata[s.key]?.error ? 'error'
          : result.stage_metadata[s.key]        ? 'ok'
          : 'skip',
  })) : [];

  const qr = result?.quality_report;

  return (
    <div className="dsp-root">
      {/* Header */}
      <div className="dsp-header">
        <div className="dsp-header-left">
          <h1 className="dsp-title">
            <span className="dsp-title-icon">🔬</span>
            Document Scanner Engine
          </h1>
          <p className="dsp-subtitle">
            Step 1 — Restore any uploaded photo to scanner-quality <em>before</em> OCR
          </p>
        </div>
        {result && (
          <div className="dsp-header-right">
            <div className="dsp-overall-score">
              <span className="dsp-overall-label">Quality Score</span>
              <span
                className="dsp-overall-value"
                style={{
                  color: qr?.quality_score >= 75 ? '#06d6a0'
                       : qr?.quality_score >= 45 ? '#ffd166'
                       : '#ff4d6d',
                }}
              >
                {Math.round(qr?.quality_score ?? 0)}
              </span>
              <span className="dsp-overall-unit">/100</span>
            </div>
          </div>
        )}
      </div>

      {/* Upload zone */}
      <div className="dsp-upload-row">
        <DropZone onFile={handleFile} disabled={loading} />

        <div className="dsp-controls">
          {file && (
            <div className="dsp-file-chip">
              <span className="dsp-file-icon">📎</span>
              <span className="dsp-file-name" title={file.name}>{file.name}</span>
              <span className="dsp-file-size">
                {(file.size / 1024).toFixed(0)} KB
              </span>
            </div>
          )}

          <label className="dsp-toggle">
            <input
              type="checkbox"
              checked={aggressive}
              onChange={e => setAggressive(e.target.checked)}
            />
            <span className="dsp-toggle-label">Aggressive enhancement</span>
            <span className="dsp-toggle-hint">(for very faded documents)</span>
          </label>

          <button
            className={`dsp-btn-restore ${loading ? 'dsp-btn-restore--loading' : ''}`}
            onClick={runRestore}
            disabled={!file || loading}
          >
            {loading ? (
              <>
                <span className="dsp-spinner" />
                Restoring…
              </>
            ) : (
              <>
                <span>🪄</span>
                Restore Document
              </>
            )}
          </button>

          {result && (
            <div className="dsp-elapsed">
              ⏱ {result.elapsed_ms?.toFixed(0)} ms
            </div>
          )}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="dsp-error">
          <span>⚠</span> {error}
        </div>
      )}

      {/* Side-by-side comparison */}
      <div className="dsp-comparison">
        <ImagePane
          title="Original"
          badge="Uploaded"
          b64={result?.original_b64}
          placeholder="Upload a document to preview"
        />

        <div className="dsp-arrow">
          {loading ? (
            <div className="dsp-arrow-spinner" />
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          )}
        </div>

        <ImagePane
          title="Restored Scan"
          badge={qr ? `Score: ${Math.round(qr.quality_score)}` : 'Awaiting'}
          b64={result?.restored_b64}
          placeholder={loading ? 'Processing…' : 'Restored output appears here'}
        />
      </div>

      {/* Pipeline stages */}
      {stages.length > 0 && (
        <div className="dsp-stages">
          <h3 className="dsp-stages-title">Pipeline Stages</h3>
          <div className="dsp-stages-row">
            {stages.map((s, i) => (
              <StageChip key={i} label={s.label} status={s.status} />
            ))}
          </div>
        </div>
      )}

      {/* Quality report */}
      {qr && (
        <div className="dsp-quality">
          <h3 className="dsp-quality-title">Quality Report</h3>
          <div className="dsp-quality-grid">
            <ScoreBadge label="Overall"     value={qr.quality_score}    />
            <ScoreBadge label="Sharpness"   value={qr.blur_score}       />
            <ScoreBadge label="Brightness"  value={qr.brightness_score} />
            <ScoreBadge label="Contrast"    value={qr.contrast_score}   />
            <ScoreBadge label="Shadow"      value={qr.shadow_score}     invert />
            <ScoreBadge label="Readability" value={qr.readability_score}/>
            <ScoreBadge label="Skew"        value={qr.skew_score}       unit="°" invert />
          </div>
          {qr.recommendation && (
            <div className="dsp-recommendation">
              <span className="dsp-rec-icon">💡</span>
              {qr.recommendation}
            </div>
          )}
        </div>
      )}

      {/* Debug info */}
      {result?.debug_session && (
        <div className="dsp-debug-info">
          <span>🗂</span> Debug frames saved →{' '}
          <code>academic_debug/{result.debug_session}/</code>
        </div>
      )}
    </div>
  );
}
