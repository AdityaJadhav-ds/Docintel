/**
 * KYCComparisonSection
 * ─────────────────────────────────────────────────────────────────────
 * Data-source contract (STRICT — never mix):
 *
 * ENTERED   = user.name  / user.original_name  / user.full_name  → DB users.full_name
 *             user.dob                                             → DB users.dob
 *             user.aadhaar_number (flat alias from list_users)     → user typed it
 *             user.pan_number     (flat alias from list_users)     → user typed it
 *
 * EXTRACTED = user.aadhaar.name / user.aadhaar.aadhaar_number / user.aadhaar.dob
 *             user.pan.name     / user.pan.pan_number           / user.pan.dob
 *             → from extracted_data table (OCR pipeline output)
 */

import { ShieldCheck, CreditCard, GitCompare } from 'lucide-react';
import VerificationCompareRow from './VerificationCompareRow';
import CrossDocumentRow from './CrossDocumentRow';

function SectionHeader({ icon: Icon, title, iconBg, iconColor, borderColor, children }) {
  return (
    <div style={{
      background: '#FFFFFF', border: '1px solid #E5E7EB',
      borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid #F3F4F6' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: iconBg, border: `1px solid ${borderColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon size={14} color={iconColor} />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>{title}</span>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function KYCComparisonSection({ user }) {
  // ─── ENTERED: strictly from DB users table fields ──────────────────────────
  const enteredName        = user?.original_name || user?.name || user?.full_name || '';
  const enteredDob         = user?.dob || '';

  // User typed these into the onboarding form.
  // Stored in users.entered_aadhaar_number / users.entered_pan_number
  // (backend returns them separately from OCR-extracted values)
  const enteredAadhaarNum  = user?.entered_aadhaar_number || '';
  const enteredPanNum      = user?.entered_pan_number     || '';

  // ─── EXTRACTED: strictly from OCR pipeline (extracted_data table) ──────────
  const extractedAadhaarName   = user?.aadhaar?.name           || '';
  const extractedAadhaarNum    = user?.aadhaar?.aadhaar_number || '';
  const extractedAadhaarDob    = user?.aadhaar?.dob            || '';

  const extractedPanName       = user?.pan?.name               || '';
  const extractedPanNum        = user?.pan?.pan_number         || '';
  const extractedPanDob        = user?.pan?.dob                || '';

  // ─── FINAL DECISION: user.final_overrides or fallback ──────────────
  const getFinal = (key, fallback) => {
    if (user?.final_overrides && user.final_overrides[key] !== undefined) {
      return user.final_overrides[key];
    }
    return fallback;
  };

  const finalName     = getFinal('name', extractedAadhaarName || extractedPanName || enteredName || '');
  const finalDob      = getFinal('dob', extractedAadhaarDob || extractedPanDob || enteredDob || '');

  const finalAadhaar  = getFinal('aadhaar', extractedAadhaarNum || enteredAadhaarNum || '');
  const finalPan      = getFinal('pan', extractedPanNum || enteredPanNum || '');
  
  const finalTenth    = getFinal('tenth', user?.academic_results?.tenth?.academic_score || user?.academic_inputs?.tenth?.percentage || '');
  const finalTwelfth  = getFinal('twelfth', user?.academic_results?.twelfth?.academic_score || user?.academic_inputs?.twelfth?.percentage || '');
  const finalDegree   = getFinal('degree', user?.academic_results?.degree?.academic_score || user?.academic_inputs?.degree?.cgpa || user?.academic_inputs?.degree?.percentage || '');
  const finalDiploma  = getFinal('diploma', user?.academic_results?.diploma?.academic_score || user?.academic_inputs?.diploma?.cgpa || user?.academic_inputs?.diploma?.percentage || '');

  // ─── UNIVERSAL CROSS-DOCUMENT CONFIGURATION ──────────────
  const verificationRows = [
    {
      id: 'name',
      label: 'Name Verification',
      sources: [
        { source: 'USER ENTERED', value: enteredName },
        { source: 'AADHAAR', value: extractedAadhaarName },
        { source: 'PAN', value: extractedPanName }
      ],
      finalValue: finalName,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('name', val)
    },
    {
      id: 'dob',
      label: 'Date of Birth Verification',
      sources: [
        { source: 'USER ENTERED', value: enteredDob },
        { source: 'AADHAAR', value: extractedAadhaarDob },
        { source: 'PAN', value: extractedPanDob }
      ],
      finalValue: finalDob,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('dob', val)
    },
    {
      id: 'aadhaar_number',
      label: 'Aadhaar Number Verification',
      sources: [
        { source: 'USER ENTERED', value: enteredAadhaarNum },
        { source: 'AADHAAR OCR', value: extractedAadhaarNum }
      ],
      finalValue: finalAadhaar,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('aadhaar', val),
      mono: true
    },
    {
      id: 'pan_number',
      label: 'PAN Number Verification',
      sources: [
        { source: 'USER ENTERED', value: enteredPanNum },
        { source: 'PAN OCR', value: extractedPanNum }
      ],
      finalValue: finalPan,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('pan', val),
      mono: true
    },
    {
      id: 'ssc_percentage',
      label: 'SSC Percentage Verification',
      sources: [
        { source: 'USER ENTERED', value: user?.academic_inputs?.tenth?.percentage ? String(user.academic_inputs.tenth.percentage) : '' },
        { source: '10TH OCR', value: user?.academic_results?.tenth?.academic_score ? String(user.academic_results.tenth.academic_score) : '' }
      ],
      finalValue: finalTenth,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('tenth', val)
    },
    {
      id: 'hsc_percentage',
      label: 'HSC Percentage Verification',
      sources: [
        { source: 'USER ENTERED', value: user?.academic_inputs?.twelfth?.percentage ? String(user.academic_inputs.twelfth.percentage) : '' },
        { source: '12TH OCR', value: user?.academic_results?.twelfth?.academic_score ? String(user.academic_results.twelfth.academic_score) : '' }
      ],
      finalValue: finalTwelfth,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('twelfth', val)
    },
    {
      id: 'degree_cgpa',
      label: 'Degree CGPA Verification',
      sources: [
        { source: 'USER ENTERED', value: (user?.academic_inputs?.degree?.cgpa || user?.academic_inputs?.degree?.percentage) ? String(user?.academic_inputs?.degree?.cgpa || user?.academic_inputs?.degree?.percentage) : '' },
        { source: 'DEGREE OCR', value: user?.academic_results?.degree?.academic_score ? String(user.academic_results.degree.academic_score) : '' }
      ],
      finalValue: finalDegree,
      onSetFinal: (val) => user?.set_final_override && user.set_final_override('degree', val)
    }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* ── AADHAAR COMPARISON ── */}
      <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '14px 18px', borderBottom: '1px solid #F3F4F6' }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: '#F0FDF4', border: '1px solid #BBF7D0', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <ShieldCheck size={14} color="#16A34A" />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>Aadhaar Verification</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#6B7280', background: '#F9FAFB', border: '1px solid #E5E7EB', padding: '2px 8px', borderRadius: 20 }}>
            Entered vs OCR Extracted
          </span>
        </div>
        <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <VerificationCompareRow
            label="Full Name"
            enteredValue={enteredName}
            extractedValue={extractedAadhaarName}
            type="text"
          />
          <VerificationCompareRow
            label="Aadhaar Number"
            enteredValue={enteredAadhaarNum}
            extractedValue={extractedAadhaarNum}
            type="id"
            mono
          />
          <VerificationCompareRow
            label="Date of Birth"
            enteredValue={enteredDob}
            extractedValue={extractedAadhaarDob}
            type="dob"
          />
        </div>
      </div>

      {/* ── PAN COMPARISON ── */}
      <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '14px 18px', borderBottom: '1px solid #F3F4F6' }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: '#EFF6FF', border: '1px solid #BFDBFE', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <CreditCard size={14} color="#2563EB" />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>PAN Verification</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#6B7280', background: '#F9FAFB', border: '1px solid #E5E7EB', padding: '2px 8px', borderRadius: 20 }}>
            Entered vs OCR Extracted
          </span>
        </div>
        <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 10 }}>
          <VerificationCompareRow
            label="Full Name"
            enteredValue={enteredName}
            extractedValue={extractedPanName}
            type="text"
          />
          <VerificationCompareRow
            label="PAN Number"
            enteredValue={enteredPanNum}
            extractedValue={extractedPanNum}
            type="id"
            mono
          />
          <VerificationCompareRow
            label="Date of Birth"
            enteredValue={enteredDob}
            extractedValue={extractedPanDob}
            type="dob"
          />
        </div>
      </div>

      {/* ── UNIVERSAL CROSS-DOCUMENT AGREEMENT ── */}
      <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '14px 18px', borderBottom: '1px solid #F3F4F6' }}>
          <div style={{ width: 28, height: 28, borderRadius: 7, background: '#FAF5FF', border: '1px solid #E9D5FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <GitCompare size={14} color="#9333EA" />
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#111827' }}>Universal Cross-Document Agreement</span>
          <span style={{ marginLeft: 'auto', fontSize: 11, fontWeight: 600, color: '#6B7280', background: '#F9FAFB', border: '1px solid #E5E7EB', padding: '2px 8px', borderRadius: 20 }}>
            All Uploaded Documents
          </span>
        </div>
        <div style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 0 }}>
          {verificationRows.map(row => (
            <CrossDocumentRow
              key={row.id}
              label={row.label}
              sources={row.sources}
              finalValue={row.finalValue}
              onSetFinal={row.onSetFinal}
              mono={row.mono}
            />
          ))}
        </div>
      </div>

    </div>
  );
}
