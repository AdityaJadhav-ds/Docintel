/**
 * VerificationCompareRow
 * ─────────────────────────────────────────────────────────────
 * Displays a strict two-source comparison:
 *   LEFT  → User-entered (from onboarding form / DB full_name / dob)
 *   RIGHT → OCR-extracted (from extracted_data table via aadhaar.* / pan.*)
 *
 * NEVER mixes the two sources.
 */

import { useState, useEffect } from 'react';
import { CheckCircle2, AlertTriangle, X, HelpCircle, Minus } from 'lucide-react';

/* ── normalise for fuzzy comparison ─── */
function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function normId(s) { return (s || '').replace(/\s/g, '').toUpperCase(); }
function normDob(s) {
  const d = (s || '').trim();
  if (d.length === 10 && (d[4] === '-' || d[4] === '/')) return d.replace(/\//g, '-');
  if (d.length === 10 && (d[2] === '-' || d[2] === '/')) {
    const p = d.replace(/\//g, '-').split('-');
    return `${p[2]}-${p[1]}-${p[0]}`;
  }
  return d;
}

function similarity(a, b) {
  const na = norm(a), nb = norm(b);
  if (!na || !nb) return 0;
  if (na === nb) return 1;
  const longer = na.length >= nb.length ? na : nb;
  const shorter = na.length < nb.length ? na : nb;
  let hits = 0;
  for (const ch of shorter) if (longer.includes(ch)) hits++;
  return hits / longer.length;
}

/* ── Status computation ─── */
function getStatus(entered, extracted, type = 'text') {
  const hasEntered = !!entered?.trim?.() || !!entered;
  const hasExtracted = !!extracted?.trim?.() || !!extracted;

  if (!hasEntered && !hasExtracted) return { key: 'NONE', label: 'Not Available', color: '#9CA3AF', bg: '#F9FAFB', border: '#E5E7EB', Icon: Minus };
  if (!hasEntered) return { key: 'NO_ENT', label: 'Extracted only', color: '#6B7280', bg: '#F9FAFB', border: '#E5E7EB', Icon: HelpCircle };
  if (!hasExtracted) return { key: 'NO_EXT', label: 'Not Extracted', color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', Icon: AlertTriangle };

  // Both present — compare
  const na = type === 'id' ? normId(entered) : type === 'dob' ? normDob(entered) : norm(entered);
  const nb = type === 'id' ? normId(extracted) : type === 'dob' ? normDob(extracted) : norm(extracted);
  const exact = na === nb;

  if (type === 'id' || type === 'dob') {
    return exact
      ? { key: 'MATCH', label: 'Match', color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0', Icon: CheckCircle2 }
      : { key: 'MISMATCH', label: 'Mismatch', color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', Icon: X };
  }

  const sim = similarity(entered, extracted);
  if (sim >= 0.92) return { key: 'MATCH', label: 'Match', color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0', Icon: CheckCircle2 };
  if (sim >= 0.65) return { key: 'PARTIAL', label: 'Slight Difference', color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', Icon: AlertTriangle };
  return { key: 'MISMATCH', label: 'Mismatch', color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', Icon: X };
}

/* ── Single value cell ─── */
function ValueCell({ title, value, mono, side, masked }) {
  const isEmpty = !value;
  const borderStyle = side === 'entered'
    ? { borderRight: '1px solid #F3F4F6' }
    : { borderLeft: '1px solid #F3F4F6' };
  const accentColor = side === 'entered' ? '#2563EB' : '#7C3AED';
  const accentBg = side === 'entered' ? '#EFF6FF' : '#F5F3FF';

  return (
    <div style={{ padding: '12px 16px', flex: 1, ...borderStyle }}>
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
        letterSpacing: '0.08em', color: accentColor,
        background: accentBg, padding: '2px 7px', borderRadius: 20, marginBottom: 8
      }}>
        {title}
      </div>
      <div style={{
        fontSize: mono ? 13 : 14, fontWeight: isEmpty ? 400 : 600,
        color: isEmpty ? '#D1D5DB' : '#0F172A',
        fontStyle: isEmpty ? 'italic' : 'normal',
        fontFamily: mono ? "'SF Mono', 'Roboto Mono', Consolas, monospace" : 'inherit',
        letterSpacing: mono ? '0.03em' : 'normal',
        wordBreak: 'break-word',
      }}>
        {isEmpty
          ? (side === 'entered' ? 'Not Provided' : 'Not Extracted')
          : value}
      </div>
    </div>
  );
}

/* ── Main export ─── */
export default function VerificationCompareRow({
  label,
  enteredValue,
  extractedValue,
  type = 'text',   // 'text' | 'id' | 'dob'
  mono = false,
  masked = false,
  extractedOnly = false,
}) {
  // If extractedOnly, we don't compare against enteredValue
  const status = extractedOnly
    ? (extractedValue
      ? { key: 'MATCH', label: 'Extracted', color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0', Icon: CheckCircle2 }
      : { key: 'NONE', label: 'Not Extracted', color: '#9CA3AF', bg: '#F9FAFB', border: '#E5E7EB', Icon: Minus })
    : getStatus(enteredValue, extractedValue, type);
  const { Icon, label: statusLabel, color, bg, border } = status;

  return (
    <div style={{
      border: '1px solid #F3F4F6',
      borderRadius: 12,
      overflow: 'hidden',
      background: '#FAFAFA',
    }}>
      {/* Field label header */}
      <div style={{
        padding: '8px 16px',
        background: '#FFFFFF',
        borderBottom: '1px solid #F3F4F6',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {label}
        </span>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          padding: '3px 10px', borderRadius: 20,
          background: bg, border: `1px solid ${border}`,
          fontSize: 11, fontWeight: 700, color,
        }}>
          <Icon size={11} />
          {statusLabel}
        </div>
      </div>

      {/* Two-column or single-column value display */}
      <div style={{ display: 'flex' }}>
        {!extractedOnly && <ValueCell title="User Entered" value={enteredValue} mono={mono} side="entered" />}
        <ValueCell title="OCR Extracted" value={extractedValue} mono={mono} side="extracted" />
      </div>
    </div>
  );
}
