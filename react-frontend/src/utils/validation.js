// ════════════════════════════════════════════════════════════════
//  DOC INTELLIGENCE — VALIDATION LOGIC
//  Single source of truth for all status / badge computation.
//  DO NOT duplicate this logic in individual components.
// ════════════════════════════════════════════════════════════════

/** Normalize a raw value for comparison (mirrors backend logic). */
export function norm(v, type) {
  if (v === null || v === undefined || v === '') return '';
  // eslint-disable-next-line no-misleading-character-class
  let s = String(v)
    .replace(/[\n\r\t]/g, '')
    .replace(/[\u200b\u200c\u200d\u2060\ufeff]/g, '')
    .replace(/ +/g, ' ')
    .trim();
  if (type === 'name')    return s.toLowerCase();
  if (type === 'aadhaar') return s.replace(/\D/g, '');
  if (type === 'pan')     return s.toUpperCase().replace(/ /g, '');
  return s;
}

/**
 * Compute the validation status for a single field.
 *
 * CASE 1: no original + OCR exists        → 'system_extracted'  (Auto Extracted)
 * CASE 2: original == OCR (normalised)    → 'matched'           (Verified)
 * CASE 3: both exist and differ           → 'needs_review'      (Needs Review)
 * CASE 4: OCR missing / invalid           → 'invalid'           (Invalid Data)
 * CASE 5: both empty                      → 'empty'
 */
export function fieldStatus(originalRaw, ocrRaw, type) {
  const o = norm(originalRaw, type);
  const e = norm(ocrRaw,      type);

  if (!o && !e) return 'empty';
  if (!e)       return 'invalid';   // OCR produced nothing
  if (!o)       return 'system_extracted'; // No original, OCR is the truth
  if (o === e)  return 'matched';
  return 'needs_review';
}

/**
 * Compute an overall record-level status from all field statuses.
 * Priority: needs_review > invalid > system_extracted > matched > empty
 */
export function recordStatus(user) {
  // final_verified is the hard DB flag — written only by APPROVE & SAVE
  if (user.final_verified) return 'matched';
  const wf = (user.workflow_state || user.status || '').toUpperCase();
  if (wf === 'VERIFIED' && user.is_verified) return 'matched';
  if (wf === 'APPROVED' && user.is_verified) return 'matched';  // legacy

  const pairs = [
    { o: user.original_name,    e: user.extracted_name    || user.name,    t: 'name'    },
    { o: user.original_aadhaar, e: user.extracted_aadhaar || user.aadhaar, t: 'aadhaar' },
    { o: user.original_pan,     e: user.extracted_pan     || user.pan,     t: 'pan'     },
  ];

  const statuses = pairs.map(({ o, e, t }) => fieldStatus(o, e, t));
  if (statuses.includes('needs_review'))    return 'needs_review';
  if (statuses.includes('invalid'))         return 'invalid';
  if (statuses.includes('system_extracted'))return 'system_extracted';
  if (statuses.every(s => s === 'matched')) return 'matched';
  return 'system_extracted'; // fallback: OCR exists but no originals
}

/**
 * Map a recordStatus key to display metadata.
 * Returns { label, icon, color, bg, border }
 */
export const STATUS_META = {
  matched: {
    label:  'Verified',
    icon:   '✓',
    color:  '#059669',
    bg:     '#ecfdf5',
    border: '#a7f3d0',
  },
  system_extracted: {
    label:  'Auto Extracted',
    icon:   '⬡',
    color:  '#2563eb',
    bg:     '#eff6ff',
    border: '#bfdbfe',
  },
  needs_review: {
    label:  'Needs Review',
    icon:   '◎',
    color:  '#d97706',
    bg:     '#fffbeb',
    border: '#fde68a',
  },
  invalid: {
    label:  'Invalid Data',
    icon:   '✕',
    color:  '#dc2626',
    bg:     '#fef2f2',
    border: '#fecaca',
  },
  empty: {
    label:  'No Data',
    icon:   '–',
    color:  '#94a3b8',
    bg:     '#f8fafc',
    border: '#e2e8f0',
  },
};

export function getStatusMeta(statusKey) {
  return STATUS_META[statusKey] || STATUS_META.empty;
}

/** Map old workflow_state strings to record status */
export function workflowToStatus(user) {
  const wf = (user.workflow_state || user.status || '').toUpperCase();
  if (wf === 'VERIFIED' && user.is_verified) return 'matched';
  if (wf === 'APPROVED' && user.is_verified) return 'matched';
  if (wf === 'REJECTED') return 'invalid';
  return recordStatus(user);
}

/** Confidence display helper */
export function confTier(confidence) {
  if (confidence == null) return null;
  const pct = Math.round(confidence * 100);
  if (pct >= 90) return { pct, label: 'High',   color: '#059669', bg: '#ecfdf5', border: '#a7f3d0' };
  if (pct >= 65) return { pct, label: 'Medium', color: '#d97706', bg: '#fffbeb', border: '#fde68a' };
  return            { pct, label: 'Low',    color: '#dc2626', bg: '#fef2f2', border: '#fecaca' };
}

/** Format a date string for display */
export function fmtDate(s) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return s; }
}
