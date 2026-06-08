/**
 * PipelineStatus.jsx — Universal Live Pipeline Indicator
 * ========================================================
 * Reusable animated stage tracker. Drop it into Upload, OCR,
 * Bulk OCR, Verification, or any multi-step async flow.
 *
 * Usage:
 *   <PipelineStatus steps={steps} variant="horizontal" />
 *   <PipelineStatus steps={steps} variant="vertical" />
 *   <PipelineStatus steps={steps} variant="compact" />
 *
 * Each step object:
 *   { id, title, icon: LucideComponent, status, durationMs? }
 *
 * status: 'idle' | 'running' | 'completed' | 'failed' | 'skipped'
 */

import { useEffect, useRef } from 'react';
import {
  CheckCircle2, XCircle, Clock, Loader,
} from 'lucide-react';

// ── colour palette (light theme) ────────────────────────────────────────────
const C = {
  idle:       { dot: '#CBD5E1', label: '#94A3B8', bg: 'transparent',   border: '#E2E8F0',  glow: 'none' },
  running:    { dot: '#4F46E5', label: '#4F46E5', bg: '#EEF2FF',        border: '#818CF8',  glow: '0 0 0 4px rgba(79,70,229,0.12)' },
  completed:  { dot: '#10B981', label: '#059669', bg: '#ECFDF5',        border: '#6EE7B7',  glow: 'none' },
  failed:     { dot: '#EF4444', label: '#DC2626', bg: '#FEF2F2',        border: '#FCA5A5',  glow: 'none' },
  skipped:    { dot: '#94A3B8', label: '#94A3B8', bg: '#F8FAFC',        border: '#E2E8F0',  glow: 'none' },
};

function SpinnerDot({ size = 14, color = '#4F46E5' }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      border: `2px solid ${color}33`,
      borderTopColor: color,
      animation: 'pipelineSpin 0.75s linear infinite',
      flexShrink: 0,
    }} />
  );
}

function StepDot({ status, size = 18 }) {
  const col = C[status] || C.idle;
  if (status === 'completed') return <CheckCircle2 size={size} color={col.dot} style={{ flexShrink: 0 }} />;
  if (status === 'failed')    return <XCircle      size={size} color={col.dot} style={{ flexShrink: 0 }} />;
  if (status === 'running')   return <SpinnerDot size={size} color={col.dot} />;
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%',
      border: `2px solid ${col.dot}`,
      flexShrink: 0, background: status === 'skipped' ? col.dot + '33' : 'transparent',
    }} />
  );
}

function formatMs(ms) {
  if (!ms || ms <= 0) return null;
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

// ── HORIZONTAL variant ───────────────────────────────────────────────────────
function HorizontalPipeline({ steps }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 0,
      overflowX: 'auto', padding: '6px 0',
    }}>
      {steps.map((step, i) => {
        const col   = C[step.status] || C.idle;
        const isLast = i === steps.length - 1;
        const Icon  = step.icon;
        const dur   = formatMs(step.durationMs);
        return (
          <div key={step.id} style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
            {/* Step pill */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 7,
              padding: '5px 12px', borderRadius: 20,
              background: col.bg,
              border: `1px solid ${col.border}`,
              boxShadow: col.glow,
              transition: 'all 0.3s ease',
            }}>
              {/* Icon */}
              {Icon && (
                <div style={{
                  width: 22, height: 22, borderRadius: 6,
                  background: col.dot + '18',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  {step.status === 'running'
                    ? <SpinnerDot size={12} color={col.dot} />
                    : <Icon size={12} color={col.dot} />
                  }
                </div>
              )}
              {!Icon && <StepDot status={step.status} size={14} />}

              {/* Title */}
              <span style={{
                fontSize: 11, fontWeight: 600,
                color: col.label,
                whiteSpace: 'nowrap',
              }}>{step.title}</span>

              {/* Duration */}
              {dur && (
                <span style={{
                  fontSize: 10, fontWeight: 500,
                  color: step.status === 'failed' ? '#EF4444' : '#94A3B8',
                  fontFamily: 'monospace',
                }}>{dur}</span>
              )}
            </div>

            {/* Connector line */}
            {!isLast && (
              <div style={{ width: 20, height: 1, flexShrink: 0, position: 'relative' }}>
                <div style={{
                  position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
                  background: step.status === 'completed' ? '#10B981' : '#E2E8F0',
                  transition: 'background 0.4s ease',
                }} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── VERTICAL variant ─────────────────────────────────────────────────────────
function VerticalPipeline({ steps }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {steps.map((step, i) => {
        const col   = C[step.status] || C.idle;
        const Icon  = step.icon;
        const dur   = formatMs(step.durationMs);
        const isLast = i === steps.length - 1;

        return (
          <div key={step.id} style={{ display: 'flex', gap: 10, position: 'relative' }}>
            {/* Left: dot + connector */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', flexShrink: 0 }}>
              <div style={{
                width: 28, height: 28, borderRadius: 8,
                background: col.bg,
                border: `1.5px solid ${col.border}`,
                boxShadow: col.glow,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 0.3s ease',
                flexShrink: 0,
              }}>
                {step.status === 'running' && !Icon && <SpinnerDot size={12} color={col.dot} />}
                {step.status === 'running' && Icon  && <SpinnerDot size={12} color={col.dot} />}
                {step.status !== 'running' && Icon  && <Icon size={13} color={col.dot} />}
                {step.status !== 'running' && !Icon && <StepDot status={step.status} size={12} />}
              </div>
              {!isLast && (
                <div style={{
                  width: 2, flex: 1, minHeight: 12,
                  background: step.status === 'completed' ? '#10B981' : '#E2E8F0',
                  borderRadius: 1, margin: '2px 0',
                  transition: 'background 0.4s ease',
                }} />
              )}
            </div>

            {/* Right: label + duration */}
            <div style={{ paddingTop: 4, paddingBottom: isLast ? 0 : 16 }}>
              <div style={{
                fontSize: 13, fontWeight: 600,
                color: col.label, lineHeight: 1.3,
                transition: 'color 0.3s',
              }}>{step.title}</div>
              {dur && (
                <div style={{
                  fontSize: 11, color: step.status === 'failed' ? '#EF4444' : '#94A3B8',
                  marginTop: 2, fontFamily: 'monospace',
                }}>{dur}</div>
              )}
              {step.error && (
                <div style={{
                  fontSize: 11, color: '#EF4444', marginTop: 3,
                  background: '#FEF2F2', padding: '3px 8px', borderRadius: 6,
                  maxWidth: 260,
                }}>{step.error}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── COMPACT variant (icon-only strip for toolbars) ───────────────────────────
function CompactPipeline({ steps }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      {steps.map((step, i) => {
        const col  = C[step.status] || C.idle;
        const Icon = step.icon;
        const isLast = i === steps.length - 1;
        return (
          <div key={step.id} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <div
              title={`${step.title}${step.durationMs ? ' — ' + formatMs(step.durationMs) : ''}`}
              style={{
                width: 26, height: 26, borderRadius: 7,
                background: col.bg,
                border: `1.5px solid ${col.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                boxShadow: col.glow,
                transition: 'all 0.3s',
                cursor: 'default',
                flexShrink: 0,
              }}
            >
              {step.status === 'running'
                ? <SpinnerDot size={11} color={col.dot} />
                : Icon
                  ? <Icon size={11} color={col.dot} />
                  : <StepDot status={step.status} size={11} />
              }
            </div>
            {!isLast && (
              <div style={{
                width: 12, height: 1.5,
                background: step.status === 'completed' ? '#10B981' : '#E2E8F0',
                borderRadius: 1, transition: 'background 0.4s',
              }} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── MODAL/OVERLAY variant ────────────────────────────────────────────────────
function ModalPipeline({ steps, title, subtitle, estimatedSeconds }) {
  const runningStep = steps.find(s => s.status === 'running');
  const doneCount   = steps.filter(s => s.status === 'completed' || s.status === 'failed').length;
  const progress    = Math.round((doneCount / steps.length) * 100);

  return (
    <div style={{
      background: '#FFFFFF',
      border: '1px solid #E2E8F0',
      borderRadius: 20,
      padding: '28px 28px 24px',
      boxShadow: '0 8px 32px rgba(15,23,42,0.08)',
      maxWidth: 420,
      width: '100%',
    }}>
      {/* Header */}
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <div style={{
          width: 52, height: 52, borderRadius: 14,
          background: '#EEF2FF',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          margin: '0 auto 14px',
        }}>
          <SpinnerDot size={24} color="#4F46E5" />
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, color: '#0F172A' }}>{title || 'Processing…'}</div>
        {runningStep && (
          <div style={{ fontSize: 13, color: '#4F46E5', marginTop: 4, fontWeight: 600 }}>
            {runningStep.title}…
          </div>
        )}
        {subtitle && !runningStep && (
          <div style={{ fontSize: 13, color: '#64748B', marginTop: 4 }}>{subtitle}</div>
        )}
        {estimatedSeconds && (
          <div style={{ fontSize: 12, color: '#94A3B8', marginTop: 6 }}>
            Usually takes {estimatedSeconds < 60 ? `${estimatedSeconds}s` : `${Math.round(estimatedSeconds/60)}m`}
          </div>
        )}
      </div>

      {/* Progress bar */}
      <div style={{ height: 4, background: '#F1F5F9', borderRadius: 99, marginBottom: 20, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${progress}%`,
          background: 'linear-gradient(90deg, #4F46E5, #818CF8)',
          borderRadius: 99,
          transition: 'width 0.5s ease',
        }} />
      </div>

      {/* Step list */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {steps.map(step => {
          const col  = C[step.status] || C.idle;
          const Icon = step.icon;
          const dur  = formatMs(step.durationMs);
          return (
            <div key={step.id} style={{
              display: 'flex', alignItems: 'center', gap: 10,
              padding: '7px 10px', borderRadius: 10,
              background: step.status === 'running' ? '#EEF2FF' : 'transparent',
              transition: 'background 0.2s',
            }}>
              <div style={{
                width: 26, height: 26, borderRadius: 7,
                background: col.bg, border: `1px solid ${col.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0, boxShadow: col.glow,
              }}>
                {step.status === 'running'
                  ? <SpinnerDot size={12} color={col.dot} />
                  : Icon ? <Icon size={12} color={col.dot} /> : <StepDot status={step.status} size={12} />
                }
              </div>
              <span style={{
                fontSize: 13, fontWeight: step.status === 'running' ? 700 : 500,
                color: col.label, flex: 1,
              }}>{step.title}</span>
              {dur && (
                <span style={{
                  fontSize: 11, color: step.status === 'failed' ? '#EF4444' : '#94A3B8',
                  fontFamily: 'monospace', flexShrink: 0,
                }}>{dur}</span>
              )}
              {step.status === 'idle' && (
                <span style={{ fontSize: 10, color: '#CBD5E1', flexShrink: 0 }}>waiting</span>
              )}
            </div>
          );
        })}
      </div>

      {/* Progress % */}
      <div style={{ textAlign: 'center', marginTop: 14 }}>
        <span style={{ fontSize: 12, color: '#94A3B8', fontWeight: 600 }}>{progress}% complete</span>
      </div>
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────────────
export default function PipelineStatus({ steps = [], variant = 'horizontal', title, subtitle, estimatedSeconds }) {
  return (
    <>
      <style>{`
        @keyframes pipelineSpin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
      {variant === 'horizontal' && <HorizontalPipeline steps={steps} />}
      {variant === 'vertical'   && <VerticalPipeline   steps={steps} />}
      {variant === 'compact'    && <CompactPipeline    steps={steps} />}
      {variant === 'modal'      && (
        <ModalPipeline steps={steps} title={title} subtitle={subtitle} estimatedSeconds={estimatedSeconds} />
      )}
    </>
  );
}
