/**
 * AcademicVerificationSection
 * ────────────────────────────────────────────────────────────────────────────
 * Renders a separate collapsible verification card for each academic document
 * type the user has uploaded.
 *
 * DATA CONTRACT (STRICT — never mix):
 *   ENTERED   = user.academic_inputs[type].percentage | .year   (from upload form → DB)
 *   EXTRACTED = academic doc OCR result from academic_engine_results table
 *                 → fetched via /api/v2/academic/list or from user.academics
 *
 * Called from UserDetailPanel with:
 *   user.academic_inputs  = { tenth: {percentage, year}, twelfth: {...}, ... }
 *   user.academics        = fetched academic_engine_results rows per type
 */

import { useState, useEffect } from 'react';
import axios from 'axios';
import { getApiBase } from '../api/api';
import {
  BookOpen, Award, FileText, GraduationCap, LayoutList,
  ChevronDown, ChevronUp, CheckCircle2, AlertTriangle, X,
  HelpCircle, Minus, Image
} from 'lucide-react';
import VerificationCompareRow from './VerificationCompareRow';

/* ─── Config per academic type ─────────────────────────── */
const ACAD_CONFIG = {
  tenth: {
    label: '10th Marksheet (SSC)',
    icon: BookOpen,
    iconBg: '#F0FDF4', iconColor: '#16A34A', iconBorder: '#BBF7D0',
    fields: [
      { key: 'percentage', label: 'CGPA / Percentage', extractedKey: 'academic_score' },
    ],
  },
  twelfth: {
    label: '12th Marksheet (HSC)',
    icon: Award,
    iconBg: '#EFF6FF', iconColor: '#2563EB', iconBorder: '#BFDBFE',
    fields: [
      { key: 'percentage', label: 'CGPA / Percentage', extractedKey: 'academic_score' },
    ],
  },
  diploma: {
    label: 'Diploma Certificate',
    icon: FileText,
    iconBg: '#FFF7ED', iconColor: '#EA580C', iconBorder: '#FED7AA',
    fields: [
      { key: 'percentage', label: 'CGPA / Percentage', extractedKey: 'academic_score' },
    ],
  },
  degree: {
    label: 'Degree Certificate',
    icon: GraduationCap,
    iconBg: '#FAF5FF', iconColor: '#9333EA', iconBorder: '#E9D5FF',
    fields: [
      { key: 'percentage', label: 'CGPA / Percentage', extractedKey: 'academic_score' },
    ],
  },
  semesters: {
    label: 'Semester Grade Cards',
    icon: LayoutList,
    iconBg: '#F0F9FF', iconColor: '#0284C7', iconBorder: '#BAE6FD',
    fields: [
      { key: 'spi', label: 'CGPA / Percentage', extractedKey: 'academic_score' },
    ],
  },
};

/* ─── status helper for a single match ─── */
function norm(s) { return (s || '').replace(/\s+/g, ' ').trim().toLowerCase(); }
function overallStatus(fields, entered, extracted) {
  let matches = 0, mismatches = 0, missing = 0;
  for (const f of fields) {
    const e = entered?.[f.key];
    const x = extracted?.[f.extractedKey];
    if (!e && !x) continue;
    if (!e || !x) { missing++; continue; }
    if (norm(String(e)) === norm(String(x))) matches++;
    else mismatches++;
  }
  if (mismatches > 0) return { label: 'Mismatch', color: '#DC2626', bg: '#FEF2F2', border: '#FECACA', Icon: X };
  if (matches > 0 && missing === 0) return { label: 'All Match', color: '#16A34A', bg: '#F0FDF4', border: '#BBF7D0', Icon: CheckCircle2 };
  if (matches > 0) return { label: 'Partial Match', color: '#D97706', bg: '#FFFBEB', border: '#FDE68A', Icon: AlertTriangle };
  return { label: 'Pending', color: '#6B7280', bg: '#F9FAFB', border: '#E5E7EB', Icon: HelpCircle };
}

/* ─── Smart label for extracted score ─── */
function resolveScoreLabel(scoreStr) {
  if (!scoreStr) return { label: 'CGPA / Percentage', display: null };
  const n = parseFloat(scoreStr);
  if (isNaN(n)) return { label: 'CGPA / Percentage', display: scoreStr };
  // Heuristic: check the DB value format (e.g. "SPI: 8.95" or plain "8.95")
  if (scoreStr.toUpperCase().startsWith('SPI')) {
    const v = scoreStr.replace(/^SPI:\s*/i, '');
    return { label: 'SPI', display: v, unit: '/10', color: '#0284C7', bg: 'linear-gradient(135deg,#F0F9FF,#BAE6FD)' };
  }
  if (scoreStr.toUpperCase().startsWith('CPI')) {
    const v = scoreStr.replace(/^CPI:\s*/i, '');
    return { label: 'CPI', display: v, unit: '/10', color: '#7C3AED', bg: 'linear-gradient(135deg,#FAF5FF,#E9D5FF)' };
  }
  if (scoreStr.toUpperCase().startsWith('CGPA')) {
    const v = scoreStr.replace(/^CGPA:\s*/i, '');
    return { label: 'CGPA', display: v, unit: '/10', color: '#9333EA', bg: 'linear-gradient(135deg,#FAF5FF,#E9D5FF)' };
  }
  // Pure numeric — <=10 = CGPA/SPI, >10 = Percentage
  if (n <= 10.0) return { label: 'CGPA / SPI', display: String(n), unit: '/10', color: '#9333EA', bg: 'linear-gradient(135deg,#FAF5FF,#E9D5FF)' };
  return { label: 'Percentage', display: String(n), unit: '%', color: '#1D4ED8', bg: 'linear-gradient(135deg,#EFF6FF,#DBEAFE)' };
}

/* ─── Single Academic Verification Card ─── */
function AcademicCard({ type, enteredInputs, extractedResult, doc, user }) {
  const [open, setOpen] = useState(true);
  const cfg = ACAD_CONFIG[type];
  if (!cfg) return null;
  const Icon = cfg.icon;

  // ── OCR extracted score ─────────────────────────────────────────
  const rawScore = extractedResult?.academic_score;
  const score = resolveScoreLabel(rawScore != null ? String(rawScore) : null);
  const hasScore = !!score.display;

  // ── User-entered score (from upload form / academic_inputs) ──────────
  // Normalize all variants: percentage | percent | cgpa | cgpi | cpi | spi
  const enteredPct  = enteredInputs?.percentage ?? enteredInputs?.percent ?? null;
  const enteredCgpa = enteredInputs?.cgpa ?? enteredInputs?.cgpi ?? enteredInputs?.cpi ?? enteredInputs?.spi ?? null;
  // Prefer cgpa over percentage; use strict checks so '0' is still treated as a value
  const enteredScoreRaw = (enteredCgpa !== null && enteredCgpa !== '') ? enteredCgpa
                        : (enteredPct  !== null && enteredPct  !== '') ? enteredPct
                        : null;
  const enteredScore = enteredScoreRaw !== null ? String(enteredScoreRaw) : '';

  // ── OCR score as plain string for VerificationCompareRow ──────────
  const extractedScoreStr = score.display ? `${score.display}${score.unit || ''}` : '';

  const confPct = extractedResult?.confidence != null
    ? Math.round((typeof extractedResult.confidence === 'object'
        ? extractedResult.confidence.overall
        : extractedResult.confidence) * 100)
    : null;

  // Status pill in header
  const statusLabel = hasScore ? 'Extracted' : (extractedResult ? 'Score not extracted' : 'Pending');
  const statusColor = hasScore ? '#16A34A' : (extractedResult ? '#D97706' : '#6B7280');
  const statusBg    = hasScore ? '#DCFCE7'  : (extractedResult ? '#FEF9C3' : '#F9FAFB');
  const statusBorder= hasScore ? '#BBF7D0'  : (extractedResult ? '#FDE68A' : '#E5E7EB');
  const StatusIcon  = hasScore ? CheckCircle2 : (extractedResult ? AlertTriangle : HelpCircle);

  // Debug log
  console.debug(`[AcademicCard] type=${type}`, {
    enteredScore,
    enteredInputs,
    rawScore,
    extractedScoreStr,
    confPct,
  });

  // ── Final Decision (DEPRECATED - Moved to Master Profile) ───────────────────
  const isPercentage = type === 'tenth' || type === 'twelfth';
  const fieldKey = isPercentage ? 'percentage' : 'cgpa';

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(15,23,42,0.03)' }}>
      {/* Header */}
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 14px', font: 'inherit' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 24, height: 24, borderRadius: 6, background: cfg.iconBg, border: `1px solid ${cfg.iconBorder}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon size={12} color={cfg.iconColor} />
          </div>
          <span style={{ fontSize: 12, fontWeight: 700, color: '#111827' }}>{cfg.label}</span>
          {confPct !== null && <span style={{ fontSize: 10, color: '#9CA3AF', fontWeight: 500 }}>&middot; OCR {confPct}%</span>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 20, background: statusBg, border: `1px solid ${statusBorder}`, fontSize: 10, fontWeight: 700, color: statusColor }}>
            <StatusIcon size={10} /> {statusLabel}
          </div>
          {open ? <ChevronUp size={14} color="#9CA3AF" /> : <ChevronDown size={14} color="#9CA3AF" />}
        </div>
      </button>

      {open && (
        <div style={{ borderTop: '1px solid #F3F4F6' }}>
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>

            {/* Entered vs OCR Comparison using VerificationCompareRow */}
            <VerificationCompareRow
              label={score.label || 'CGPA / Percentage'}
              enteredValue={enteredScore}
              extractedValue={extractedScoreStr}
              type="text"
            />

          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Multi-semester list ─── */
function SemesterCard({ semFiles, extractedResults }) {
  const [open, setOpen] = useState(true);
  const cfg = ACAD_CONFIG.semesters;
  const Icon = cfg.icon;

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 4px rgba(15,23,42,0.04)' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{ width: '100%', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '13px 18px', font: 'inherit' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: cfg.iconBg, border: `1px solid ${cfg.iconBorder}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon size={14} color={cfg.iconColor} />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>{cfg.label}</span>
          <span style={{ fontSize: 11, color: '#9CA3AF' }}>· {semFiles?.length || 0} uploaded</span>
        </div>
        {open ? <ChevronUp size={16} color="#9CA3AF" /> : <ChevronDown size={16} color="#9CA3AF" />}
      </button>

      {open && (
        <div style={{ borderTop: '1px solid #F3F4F6', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {semFiles && semFiles.length > 0 ? (
            semFiles.map((sem, idx) => {
              const ext = extractedResults?.[idx];
              return (
                <div key={idx} style={{ border: '1px solid #F3F4F6', borderRadius: 10, overflow: 'hidden', background: '#FAFAFA' }}>
                  <div style={{ padding: '8px 14px', background: '#F8FAFC', borderBottom: '1px solid #F3F4F6', fontSize: 12, fontWeight: 700, color: '#475569' }}>
                    {sem.semester || `Semester ${idx + 1}`}
                  </div>
                  <div style={{ padding: '10px 14px' }}>
                    <VerificationCompareRow
                      label="SGPA / SPI"
                      enteredValue={sem.spi ? String(sem.spi) : ''}
                      extractedValue={ext?.cgpa ? String(ext.cgpa) : ''}
                      type="text"
                      extractedOnly={true}
                    />
                  </div>
                </div>
              );
            })
          ) : (
            <div style={{ textAlign: 'center', padding: '20px 0', fontSize: 12, color: '#94A3B8' }}>No semester cards uploaded</div>
          )}
        </div>
      )}
    </div>
  );
}

/* ─── MAIN EXPORT ─────────────────────────────────────────── */
export default function AcademicVerificationSection({ user }) {
  // user.academic_inputs = what was typed in the upload form (entered)
  // user.academic_docs   = documents[] fetched from DB for this user (includes storage_path)
  // user.academic_results = academic_engine_results[] linked by user_id or doc_id

  const acadInputs  = user?.academic_inputs  || {};  // { tenth: {percentage, year}, ... }
  const acadDocs    = user?.academic_docs    || [];   // documents with doc_type in [tenth, twelfth, degree, diploma]
  const acadResults = user?.academic_results || {};   // { tenth: {percentage, cgpa, passing_year, ...}, ... }
  const semFiles    = user?.semester_files   || [];   // [{semester, spi, preview_url}]
  const semResults  = user?.semester_results || [];   // extracted results per semester

  // Which types are present (have documents)
  const docTypeSet = new Set(acadDocs.map(d => d.doc_type).filter(Boolean));
  const hasSemesters = semFiles.length > 0 || docTypeSet.has('semesters') || docTypeSet.has('semester');

  const activeTypes = ['tenth', 'twelfth', 'diploma', 'degree'].filter(t => docTypeSet.has(t) || acadInputs[t]);

  // If nothing at all
  if (activeTypes.length === 0 && !hasSemesters) {
    return (
      <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 3px rgba(15,23,42,0.04)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '14px 18px' }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: '#F1F5F9', border: '1px solid #E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <GraduationCap size={14} color="#94A3B8" />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#374151' }}>Academic Verification</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#94A3B8', background: '#F9FAFB', border: '1px solid #E5E7EB', padding: '2px 8px', borderRadius: 20 }}>
            No Academic Records
          </span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Section header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 2px 8px' }}>
        <div style={{ width: 28, height: 28, borderRadius: 7, background: '#FAF5FF', border: '1px solid #E9D5FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <GraduationCap size={14} color="#9333EA" />
        </div>
        <span style={{ fontSize: 13, fontWeight: 800, color: '#111827', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Academic Verification</span>
        <span style={{ fontSize: 11, fontWeight: 600, color: '#9333EA', background: '#FAF5FF', border: '1px solid #E9D5FF', padding: '2px 8px', borderRadius: 20, marginLeft: 'auto' }}>
          {activeTypes.length + (hasSemesters ? 1 : 0)} document type{activeTypes.length + (hasSemesters ? 1 : 0) !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Cards per type */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {activeTypes.map(type => (
          <AcademicCard
            key={type}
            type={type}
            enteredInputs={acadInputs[type] || {}}
            extractedResult={acadResults[type] || null}
            doc={acadDocs.find(d => d.doc_type === type) || null}
            user={user}
          />
        ))}
        {hasSemesters && (
          <SemesterCard semFiles={semFiles} extractedResults={semResults} />
        )}
      </div>
    </div>
  );
}
