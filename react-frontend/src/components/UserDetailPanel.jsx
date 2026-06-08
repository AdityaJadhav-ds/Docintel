/**
 * UserDetailPanel — Enterprise KYC + Academic Verification Workspace
 * ─────────────────────────────────────────────────────────────────────
 * Layout:
 *   Top bar      → navigation + action buttons
 *   Left panel   → document preview (Aadhaar / PAN tabs)
 *   Right panel  → scrollable verification data:
 *                    1. Candidate summary header
 *                    2. KYC Comparison (entered vs extracted)
 *                    3. Academic Verification
 *                    4. OCR Insights
 *                    5. Risk Assessment
 *                    6. Audit Timeline
 *
 * DATA CONTRACT:
 *   ENTERED   = user.original_name | user.name | user.full_name → users.full_name in DB
 *               user.dob                                         → users.dob in DB
 *   EXTRACTED = user.aadhaar.* | user.pan.*                      → extracted_data (OCR)
 *   ACADEMIC  = user.academic_results[type]                      → academic_engine_results
 *               user.academic_inputs[type]                       → upload form entries
 *
 * NEVER cross-fill sources.
 */

import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { submitUserAction, getApiBase, apiReprocessOCR } from '../api/api';
import { useToast } from '../context/NotificationContext';
import {
  X, ArrowLeft, ArrowRight, RefreshCw,
  Check, CheckCircle2, XCircle, SkipForward, FileText,
  User, Calendar, Hash, Clock, TrendingUp, ShieldCheck, CreditCard, AlertTriangle,
} from 'lucide-react';

import ReviewDocumentViewer      from './ReviewDocumentViewer';
import KYCComparisonSection      from './KYCComparisonSection';
import OCRInsightsSection        from './OCRInsightsSection';
import RiskAssessmentSection     from './RiskAssessmentSection';
import AuditTimelineSection      from './AuditTimelineSection';
import MasterProfileSection      from './MasterProfileSection';

import './KYCWorkspace.css';

/* ─── Keyboard navigation ────────────────────────────────── */
function useKeyNav(isOpen, { onClose, onNext, onPrev, hasNext, hasPrev }) {
  useEffect(() => {
    const h = (e) => {
      if (!isOpen) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowRight' && hasNext) onNext?.();
      if (e.key === 'ArrowLeft'  && hasPrev) onPrev?.();
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [isOpen, onClose, onNext, onPrev, hasNext, hasPrev]);
}

/* ─── Status badge ──────────────────────────────────────── */
function StatusBadge({ state }) {
  const map = {
    VERIFIED:        { label: 'Verified',      cls: 'badge-green'  },
    APPROVED:        { label: 'Verified',      cls: 'badge-green'  },
    REJECTED:        { label: 'Rejected',       cls: 'badge-red'    },
    REVIEW_REQUIRED: { label: 'Manual Review',  cls: 'badge-yellow' },
    PROCESSING:      { label: 'Processing',     cls: 'badge-blue'   },
    UPLOADED:        { label: 'Pending Review', cls: 'badge-gray'   },
    PENDING:         { label: 'Pending Review', cls: 'badge-gray'   },
  };
  const cfg = map[state] || map.PENDING;
  return <span className={`badge ${cfg.cls}`}>{cfg.label}</span>;
}

/* ─── Candidate header ──────────────────────────────────── */
function CandidateSummaryHeader({ user }) {
  // ENTERED name: always from DB users.full_name (never OCR)
  const enteredName = user?.original_name || user?.name || user?.full_name || 'Unknown Candidate';
  const enteredDob  = user?.dob || '—';
  const state       = user?.workflow_state || user?.status || 'PENDING';
  const conf        = user?.confidence || 0;
  const id          = user?.id;

  const initials = enteredName.split(' ').filter(Boolean).slice(0, 2).map(w => w[0]).join('').toUpperCase();

  const confColor = conf >= 85 ? '#16A34A' : conf >= 60 ? '#D97706' : '#DC2626';

  const fmtDate = (ts) => {
    if (!ts) return '—';
    try { return new Date(ts).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }); }
    catch { return ts; }
  };

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E5E7EB', borderRadius: 16, padding: '20px 24px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        {/* Avatar */}
        <div style={{
          width: 52, height: 52, borderRadius: 14,
          background: 'linear-gradient(135deg, #EFF6FF, #DBEAFE)',
          border: '1.5px solid #BFDBFE',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 18, fontWeight: 700, color: '#2563EB', flexShrink: 0,
        }}>
          {initials}
        </div>

        {/* Identity */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            <h2 style={{ fontSize: 18, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.02em' }}>
              {enteredName}
            </h2>
            <StatusBadge state={state} />
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            {id      && <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#6B7280' }}><Hash size={12} color="#9CA3AF" /> ID #{id}</span>}
            {enteredDob !== '—' && <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#6B7280' }}><Calendar size={12} color="#9CA3AF" /> DOB: {enteredDob}</span>}
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#6B7280' }}><Clock size={12} color="#9CA3AF" /> {fmtDate(user?.created_at)}</span>
          </div>
        </div>

        {/* OCR Confidence */}
        {conf > 0 && (
          <div style={{ flexShrink: 0, borderLeft: '1px solid #F3F4F6', paddingLeft: 20 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 6 }}>
              OCR Confidence
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 72, height: 5, borderRadius: 3, background: '#F3F4F6', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${conf}%`, background: confColor, transition: 'width 0.6s ease' }} />
              </div>
              <span style={{ fontSize: 14, fontWeight: 700, color: confColor }}>{Math.round(conf)}%</span>
            </div>
          </div>
        )}
      </div>

      {/* Contact Info */}
      <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 16, background: '#F8FAFC', padding: '12px 16px', borderRadius: 12, border: '1px solid #E2E8F0' }}>
        {(() => {
          // STRICT MAPPING: Only read from registration profile, never OCR
          const profileData = {
            email: user?.profile?.email || user?.email || "",
            mobile: user?.profile?.mobile_number || user?.mobile_number || "",
            address: user?.profile?.address || user?.permanent_address || ""
          };

          const email   = profileData.email   !== "" ? profileData.email   : null;
          const mobile  = profileData.mobile  !== "" ? profileData.mobile  : null;
          const address = profileData.address !== "" ? profileData.address : null;

          return (
            <>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Email Address</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: email ? '#0F172A' : '#94A3B8' }}>
                  {email || 'Not Provided'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Mobile Number</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: mobile ? '#0F172A' : '#94A3B8' }}>
                  {mobile || 'Not Provided'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>Permanent Address</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: address ? '#0F172A' : '#94A3B8', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={address || ''}>
                  {address || 'Not Provided'}
                </div>
              </div>
            </>
          );
        })()}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════ */
export default function UserDetailPanel({
  user, isOpen, onClose, onActionSuccess, onNext, onPrev, hasPrev, hasNext,
}) {
  const toast   = useToast();
  const apiBase = getApiBase();

  const [docs, setDocs]               = useState({ aadhaar: null, pan: null });
  const [acadDocs, setAcadDocs]       = useState([]);
  const [acadResults, setAcadResults] = useState({});
  const [acadInputs, setAcadInputs]   = useState({});   // user-entered scores, rebuilt from doc rows
  const [docsLoading, setDocsLoading] = useState(false);
  const [isSuccessCheck, setIsSuccessCheck] = useState(false);
  const [isFadingOut, setIsFadingOut]       = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [activeDoc, setActiveDoc]           = useState('aadhaar');
  const [finalOverrides, setFinalOverrides] = useState({});

  const handleSetFinal = (field, value) => {
    setFinalOverrides(prev => ({ ...prev, [field]: value }));
  };

  useKeyNav(isOpen, { onClose, onNext, onPrev, hasNext, hasPrev });

  /* Lock body scroll */
  useEffect(() => {
    document.body.style.overflow = isOpen ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  /* ── Fetch documents + signed URLs ─────────────────────── */
  const ACAD_TYPES = ['tenth', 'twelfth', 'diploma', 'degree', 'semester', 'semesters'];

  const fetchDocs = useCallback(async () => {
    if (!user?.id) return;
    setDocsLoading(true);
    try {
      const res = await axios.get(`${apiBase}/users/${user.id}/documents`, { timeout: 10000 });
      const list = res.data?.documents || [];

      // ── KYC docs (Aadhaar / PAN) ──────────────────────────────
      const p = { aadhaar: null, pan: null };
      for (const d of list) {
        if (d.doc_type === 'aadhaar' && !p.aadhaar) p.aadhaar = d;
        if (d.doc_type === 'pan'     && !p.pan)     p.pan = d;
      }
      for (const type of ['aadhaar', 'pan']) {
        if (p[type] && !p[type].signed_url && p[type].storage_path) {
          try {
            const r = await axios.get(`${apiBase}/signed-url`, {
              params: { storage_path: p[type].storage_path, expires_in: 7200 },
              timeout: 8000,
            });
            if (r.data?.signed_url) p[type] = { ...p[type], signed_url: r.data.signed_url };
          } catch (_) {}
        }
      }
      setDocs(p);

      // ── Academic docs ──────────────────────────────────────────
      const aList = list.filter(d => ACAD_TYPES.includes(d.doc_type));
      // Generate signed URLs for academic docs
      const aEnriched = await Promise.all(
        aList.map(async (d) => {
          if (d.signed_url || !d.storage_path) return d;
          try {
            const r = await axios.get(`${apiBase}/signed-url`, {
              params: { storage_path: d.storage_path, expires_in: 7200 },
              timeout: 8000,
            });
            if (r.data?.signed_url) return { ...d, signed_url: r.data.signed_url };
          } catch (_) {}
          return d;
        })
      );
      setAcadDocs(aEnriched);

      // ── Build academic results map from extracted_data columns ─────────────
      // Academic docs saved via /api/users/{id}/documents/upload use extracted_data
      // with column mapping:
      //   extracted_percentage → OCR percentage (aadhaar_number column repurposed)
      //   extracted_grade      → OCR CGPA/SPI (pan_number column repurposed)
      //   extracted_name       → OCR candidate name
      //   extracted_year       → OCR passing year
      //   ocr_confidence       → pipeline confidence (0.0–1.0)
      //
      // Build resultMap: { tenth: {percentage, cgpa, candidate_name, passing_year, confidence}, ... }
      const resultMap = {};
      for (const doc of aEnriched) {
        const type = doc.doc_type;  // e.g. 'tenth', 'twelfth', 'degree', 'semester'
        if (!type) continue;
        // Normalize to AcademicVerificationSection keys
        const pct   = doc.extracted_percentage || null;
        const grade = doc.extracted_grade || null;
        const name  = doc.extracted_candidate_name || null;
        const conf  = doc.ocr_confidence != null ? doc.ocr_confidence : null;
        
        let academic_score = grade || pct;

        // Create entry to indicate OCR has run
        const key = type === 'semester' ? 'semesters' : type;
        if (!resultMap[key]) {
          resultMap[key] = {
            academic_score: academic_score,
            candidate_name: name,
            confidence:    conf,
          };
        }

        console.log(
          `[UserDetailPanel] academic doc type=${type} score=${academic_score} name=${name} conf=${conf}`
        );
      }

      console.log('[UserDetailPanel] acadResults from extracted_data:', resultMap);
      setAcadResults(resultMap);

      // ── Build academic_inputs from entered_percentage on each academic doc ──
      // 'entered_percentage' is stored in users.academic_inputs JSONB and
      // returned by the backend on each doc row. Merge with existing user.academic_inputs.
      let baseInputs = user?.academic_inputs || {};
      if (typeof baseInputs === 'string') {
        try { baseInputs = JSON.parse(baseInputs); } catch (e) { baseInputs = {}; }
      }
      const inputsMap = { ...baseInputs };
      for (const doc of aEnriched) {
        const type = doc.doc_type;
        if (!type) continue;
        const enteredPct = doc.entered_percentage;
        if (enteredPct != null && enteredPct !== '') {
          inputsMap[type] = { percentage: String(enteredPct) };
        }
      }
      console.log('[UserDetailPanel] academic_inputs from docs:', inputsMap);
      // Store in a ref that enriched object can read
      setAcadInputs(inputsMap);

    } catch (err) {
      console.warn('[KYCPanel] Could not fetch docs:', err.message);
    } finally {
      setDocsLoading(false);
    }
  }, [user?.id, apiBase]);

  useEffect(() => {
    if (isOpen && user?.id) {
      setDocs({ aadhaar: null, pan: null });
      setAcadDocs([]);
      setAcadResults({});
      setAcadInputs({});
      setFinalOverrides({});
      fetchDocs();
    }
  }, [isOpen, user?.id]);

  useEffect(() => {
    if (user) setActiveDoc('aadhaar');
  }, [user?.id]);

  /* ── Dynamic Tabs ───────────────────────────────────────── */
  const acadLabels = {
    tenth: '10th', twelfth: '12th', diploma: 'Diploma', degree: 'Degree',
    semester: 'Semester', semesters: 'Semesters'
  };

  const availableTabs = [];
  if (docs.aadhaar) availableTabs.push({ id: 'aadhaar', label: 'Aadhaar', doc: docs.aadhaar });
  if (docs.pan)     availableTabs.push({ id: 'pan',     label: 'PAN',     doc: docs.pan });
  
  const typeCounts = {};
  acadDocs.forEach(d => {
    if (d.doc_type) {
      typeCounts[d.doc_type] = (typeCounts[d.doc_type] || 0) + 1;
      const isDuplicate = typeCounts[d.doc_type] > 1;
      const tabId = isDuplicate ? `${d.doc_type}_${typeCounts[d.doc_type]}` : d.doc_type;
      const labelSuffix = isDuplicate ? ` ${typeCounts[d.doc_type]}` : '';
      
      availableTabs.push({
        id: tabId,
        label: (acadLabels[d.doc_type] || d.doc_type) + labelSuffix,
        doc: d
      });
    }
  });

  // Fallback if no docs are loaded yet, but we want to show Aadhaar/PAN tabs during loading
  if (availableTabs.length === 0 && docsLoading) {
    availableTabs.push({ id: 'aadhaar', label: 'Aadhaar', doc: null });
    availableTabs.push({ id: 'pan', label: 'PAN', doc: null });
  }

  // Ensure activeDoc is valid
  const currentTab = availableTabs.find(t => t.id === activeDoc) || availableTabs[0];
  const currentDoc = currentTab?.doc || null;
  const currentLabel = currentTab?.label || 'Document';

  /* ── Actions ────────────────────────────────────────────── */
  const handleAction = async (action) => {
    if (!user) return;
    try {
      let payloadData = {};
      if (action === 'APPROVED') {
        const extractStr = (val) => val && typeof val === 'object' ? (val.value || '') : (val || '');
        const ocrName = extractStr(user.aadhaar?.name || user.pan?.name || '').trim() || null;
        const finalPercentage = extractStr(user.academic_results?.tenth?.academic_score
          || user.academic_results?.twelfth?.academic_score) || null;
        const finalCgpa = extractStr(user.academic_results?.degree?.academic_score
          || user.academic_results?.diploma?.academic_score
          || user.academic_results?.semesters?.academic_score) || null;

        // APPROVE & SAVE: Use overridden values or fall back to OCR > entered
        payloadData = {
          name:       finalOverrides.name !== undefined ? finalOverrides.name : (ocrName || extractStr(user.name) || extractStr(user.full_name)),
          aadhaar:    finalOverrides.aadhaar !== undefined ? finalOverrides.aadhaar : (extractStr(user.aadhaar?.aadhaar_number) || extractStr(user.entered_aadhaar_number) || null),
          pan:        finalOverrides.pan !== undefined ? finalOverrides.pan : (extractStr(user.pan?.pan_number) || extractStr(user.entered_pan_number) || null),
          dob:        finalOverrides.dob !== undefined ? finalOverrides.dob : (extractStr(user.aadhaar?.dob) || extractStr(user.pan?.dob) || extractStr(user.dob) || null),
          percentage: finalOverrides.percentage !== undefined ? finalOverrides.percentage : finalPercentage,
          cgpa:       finalOverrides.cgpa !== undefined ? finalOverrides.cgpa : finalCgpa,
          tenth:      finalOverrides.tenth !== undefined ? finalOverrides.tenth : (extractStr(user.academic_results?.tenth?.academic_score) || extractStr(user.academic_inputs?.tenth?.percentage) || null),
          twelfth:    finalOverrides.twelfth !== undefined ? finalOverrides.twelfth : (extractStr(user.academic_results?.twelfth?.academic_score) || extractStr(user.academic_inputs?.twelfth?.percentage) || null),
          degree:     finalOverrides.degree !== undefined ? finalOverrides.degree : (extractStr(user.academic_results?.degree?.academic_score) || extractStr(user.academic_inputs?.degree?.cgpa) || extractStr(user.academic_inputs?.degree?.percentage) || null),
          diploma:    finalOverrides.diploma !== undefined ? finalOverrides.diploma : (extractStr(user.academic_results?.diploma?.academic_score) || extractStr(user.academic_inputs?.diploma?.cgpa) || extractStr(user.academic_inputs?.diploma?.percentage) || null),
          email:      finalOverrides.email !== undefined ? finalOverrides.email : (extractStr(user.email) || null),
          mobile:     finalOverrides.mobile !== undefined ? finalOverrides.mobile : (extractStr(user.mobile_number) || null),
          address:    finalOverrides.address !== undefined ? finalOverrides.address : (extractStr(user.permanent_address) || null),
        };
      } else {
        payloadData = {
          name:    user.original_name || user.name || user.full_name,
          aadhaar: user.entered_aadhaar_number,
          pan:     user.entered_pan_number,
          dob:     user.dob,
        };
      }

      const res = await submitUserAction(user.id, action, payloadData);

      // dbUser is the re-fetched canonical DB row returned by the backend
      const dbUser = res?.user || {};

      // Canonical display name: backend already wrote final_name/full_name to DB
      const canonicalName = dbUser.final_name || dbUser.full_name || payloadData.name || user.name;

      const updated = {
        ...user,
        ...dbUser,                        // overwrite with real DB values
        name:          canonicalName,
        original_name: canonicalName,
        full_name:     canonicalName,
        entered_aadhaar_number: dbUser.aadhaar_number || user.entered_aadhaar_number,
        entered_pan_number:     dbUser.pan_number     || user.entered_pan_number,
        workflow_state: dbUser.workflow_state || (action === 'APPROVED' ? 'VERIFIED' : action),
        status:         dbUser.status         || (action === 'APPROVED' ? 'VERIFIED' : action),
        is_verified:    dbUser.is_verified    ?? (action === 'APPROVED' ? 1 : 0),
        final_verified: dbUser.final_verified ?? (action === 'APPROVED'),
        _softRetain: true,
        _optimistic: false,              // not optimistic — this came from DB
      };

      toast(
        action === 'APPROVED' ? '✔ Verification approved and final data saved' :
        action === 'REJECTED' ? 'Verification rejected' : 'Sent for manual review',
        action === 'APPROVED' ? 'success' : 'info'
      );
      setIsSuccessCheck(true);
      setTimeout(() => setIsFadingOut(true), 150);
      setTimeout(() => {
        onActionSuccess(updated);
        setIsFadingOut(false);
        setIsSuccessCheck(false);
      }, 300);
    } catch (err) {
      toast(err.message || 'Failed to save verification state', 'error');
    }
  };

  const handleReprocess = async () => {
    if (!user?.id || isReprocessing) return;
    setIsReprocessing(true);
    try {
      await apiReprocessOCR(user.id);
      toast('OCR re-processing queued — refresh in ~30s', 'info');
    } catch (err) {
      toast(err.message || 'Re-processing failed', 'error');
    } finally {
      setIsReprocessing(false);
    }
  };

  if (!user || !isOpen) return null;

  // ── Real-time Dirty State Detection ─────────────────────────────────────────
  //
  // RULE: currentFinalData MUST mirror MasterProfileSection.getFinal() exactly:
  //   priority: finalOverrides[key] → user.final_key (DB approved) → OCR fallback
  //
  // RULE: verifiedSnapshot is read from user.final_verified_data (JSONB deep-clone
  //   written at approval time), falling back to individual final_* columns.

  const _xStr = (val) => {
    if (!val) return '';
    if (typeof val === 'object') return String(val.value ?? '');
    try {
      const p = JSON.parse(val);
      if (p && typeof p === 'object' && p.value !== undefined) return String(p.value);
    } catch (_) {}
    return String(val);
  };

  // ── Parse the JSONB snapshot stored at approval time ─────────────────────────
  const _jsonbSnap = (() => {
    const raw = user.final_verified_data;
    if (!raw) return {};
    if (typeof raw === 'object') return raw; // already parsed by Supabase client
    try { return JSON.parse(raw); } catch (_) { return {}; }
  })();

  // ── verifiedSnapshot: JSONB blob wins; individual columns are fallback ────────
  const verifiedSnapshot = {
    name:       _xStr(_jsonbSnap.name)       || _xStr(user.final_name)       || '',
    aadhaar:    _xStr(_jsonbSnap.aadhaar)    || _xStr(user.final_aadhaar)    || '',
    pan:        _xStr(_jsonbSnap.pan)        || _xStr(user.final_pan)        || '',
    dob:        _xStr(_jsonbSnap.dob)        || _xStr(user.final_dob)        || '',
    percentage: _xStr(_jsonbSnap.percentage) || _xStr(user.final_percentage) || '',
    cgpa:       _xStr(_jsonbSnap.cgpa)       || _xStr(user.final_cgpa)       || '',
  };

  // ── OCR/entered fallbacks (used only when no DB final_* value exists) ─────────
  const _ocrName    = _xStr(user.aadhaar?.name || user.pan?.name || '').trim();
  const _ocrAadhaar = _xStr(user.aadhaar?.aadhaar_number || user.entered_aadhaar_number || '');
  const _ocrPan     = _xStr(user.pan?.pan_number || user.entered_pan_number || '');
  const _ocrDob     = _xStr(user.aadhaar?.dob || user.pan?.dob || user.dob || '');
  const _ocrPct     = _xStr(user.academic_results?.tenth?.academic_score || user.academic_results?.twelfth?.academic_score || '');
  const _ocrCgpa    = _xStr(user.academic_results?.degree?.academic_score || user.academic_results?.diploma?.academic_score || user.academic_results?.semesters?.academic_score || '');

  // ── getFinal: exact mirror of MasterProfileSection.getFinal() ────────────────
  //   finalOverrides[key]  →  user.final_key (DB)  →  OCR fallback
  const _getFinal = (key, ocrFallback) => {
    if (finalOverrides[key] !== undefined) return String(finalOverrides[key]);
    if (user[`final_${key}`]) return _xStr(user[`final_${key}`]);
    return ocrFallback;
  };

  // ── currentFinalData: exactly what MasterProfileSection displays right now ────
  const currentFinalData = {
    name:       _getFinal('name',       _ocrName),
    aadhaar:    _getFinal('aadhaar',    _ocrAadhaar),
    pan:        _getFinal('pan',        _ocrPan),
    dob:        _getFinal('dob',        _ocrDob),
    percentage: _getFinal('percentage', _ocrPct),
    cgpa:       _getFinal('cgpa',       _ocrCgpa),
  };

  // ── Normalise: trim + lowercase before comparing ─────────────────────────────
  const _norm = (obj) => {
    const r = {};
    for (const [k, v] of Object.entries(obj)) r[k] = (v || '').toString().trim().toLowerCase();
    return r;
  };

  const _wasVerified = !!user.final_verified;

  // If never approved → always Approve & Save
  // If approved → compare current values against stored snapshot deeply
  const isDirty = !_wasVerified
    ? true
    : JSON.stringify(_norm(currentFinalData)) !== JSON.stringify(_norm(verifiedSnapshot));

  // isApproved: DB says verified AND current values still match the approved snapshot
  const isApproved = _wasVerified && !isDirty;

  // Derive semester arrays directly from acadDocs state
  const semesterFilesList = [];
  const semesterResultsList = [];
  const semesterDocs = acadDocs.filter(d => d.doc_type === 'semester').reverse(); // oldest first
  semesterDocs.forEach((doc, idx) => {
    semesterFilesList.push({
      semester: `Semester ${idx + 1}`,
      spi: doc.entered_percentage || null,
      preview_url: doc.signed_url
    });
    semesterResultsList.push({
      cgpa: doc.extracted_grade || doc.extracted_percentage || null,
      confidence: doc.ocr_confidence
    });
  });

  // Helper to recursively unwrap {"value": "...", "confidence": ...} or JSON strings of it
  const cleanOcrData = (obj) => {
    if (!obj) return obj;
    if (typeof obj === 'string') {
      try {
        const p = JSON.parse(obj);
        if (p && typeof p === 'object' && p.value !== undefined) return String(p.value);
      } catch (e) {}
      return obj;
    }
    if (typeof obj === 'object') {
      if (Array.isArray(obj)) return obj.map(cleanOcrData);
      if (obj.value !== undefined) return String(obj.value); // Unwrap
      const res = {};
      for (const [k, v] of Object.entries(obj)) res[k] = cleanOcrData(v);
      return res;
    }
    return obj;
  };

  // Build enriched — keep all data sources strictly isolated.
  // NEVER let OCR values bleed into "entered" fields.
  const enriched = {
    ...user,

    // ── OCR sub-objects (from extracted_data / documents endpoint) ──────────
    aadhaar: cleanOcrData({ ...(user.aadhaar || {}), ...(docs.aadhaar?.extracted || {}) }),
    pan:     cleanOcrData({ ...(user.pan     || {}), ...(docs.pan?.extracted     || {}) }),

    // ── Entered fields: ONLY from what the backend explicitly marks as "entered_" ──
    // These come from users.aadhaar_number / users.pan_number (form inputs).
    // If the migration hasn't added those columns yet, these will be empty strings
    // and the UI will correctly show "Not Provided" — not fall back to OCR values.
    entered_aadhaar_number: user.entered_aadhaar_number ?? '',
    entered_pan_number:     user.entered_pan_number     ?? '',

    // ── OCR flat aliases (for non-comparison displays) ────────────────────────
    // These are OCR-only. KYCComparisonSection reads entered_* not these.
    aadhaar_number: user.ocr_aadhaar_number || user.aadhaar?.aadhaar_number || '',
    pan_number:     user.ocr_pan_number     || user.pan?.pan_number         || '',

    // ── Name & DOB: always from registration form (users table) ──────────────
    // Never auto-fill from OCR.
    name:          user.full_name || user.original_name || user.name || '',
    original_name: user.full_name || user.original_name || user.name || '',
    dob:           user.dob || '',   // registration DOB only

    // ── Academic data — all three sources isolated, never cross-filled ────────
    academic_inputs:  acadInputs,           // user-entered scores (rebuilt from doc.entered_percentage)
    academic_docs:    acadDocs,             // documents[] with signed_url
    academic_results: cleanOcrData(acadResults),          // OCR engine results per type
    semester_files:   semesterFilesList,
    semester_results: cleanOcrData(semesterResultsList),
    
    // ── Final Decision State ────────
    final_overrides: finalOverrides,
    set_final_override: handleSetFinal,
  };

  // Debug log — dirty state tracing (open DevTools console to inspect)
  console.debug('[DirtyState]', {
    id: user.id, _wasVerified, isDirty, isApproved,
    verifiedSnapshot, currentFinalData, finalOverrides,
    final_verified_data: user.final_verified_data,
  });


  // Display name in top bar: ALWAYS entered name
  const displayName = enriched.original_name || enriched.name || enriched.full_name || 'Unknown';

  return (
    <div className="kyc-overlay" onClick={onClose}>
      <div
        className="kyc-workspace"
        onClick={e => e.stopPropagation()}
        style={{
          opacity: isFadingOut ? 0 : 1,
          transform: isFadingOut ? 'translateY(-8px) scale(0.99)' : 'translateY(0) scale(1)',
          transition: 'opacity 200ms ease, transform 200ms ease',
        }}
      >
        {/* ── Top bar ────────────────────────────────────────── */}
        <div className="kyc-topbar">
          <div className="kyc-topbar-left">
            <div className="kyc-brand-mark"><span>KYC</span></div>
            <span className="kyc-topbar-title">Verification Review</span>
            <span className="kyc-topbar-sep">/</span>
            <span className="kyc-topbar-user">{displayName}</span>
          </div>

          <div className="kyc-topbar-right">
            <button className="kyc-nav-btn" disabled={!hasPrev} onClick={onPrev} title="Previous (←)">
              <ArrowLeft size={15} />
            </button>
            <button className="kyc-nav-btn" disabled={!hasNext} onClick={onNext} title="Next (→)">
              <ArrowRight size={15} />
            </button>

            <div className="kyc-divider" />

            {isApproved ? (
              <div className="kyc-btn-verified" title="All final values match the verified snapshot">
                <CheckCircle2 size={14} /> Verified
              </div>
            ) : (
              <>
                {/* Show a Review badge when previously approved but fields have changed */}
                {_wasVerified && isDirty && (
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '3px 10px', borderRadius: 20,
                    background: '#FEF3C7', border: '1px solid #FCD34D',
                    fontSize: 11, fontWeight: 700, color: '#D97706'
                  }}>
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: '#F59E0B', display: 'inline-block' }} />
                    Review Required
                  </div>
                )}
                <button className="kyc-btn-approve" onClick={() => handleAction('APPROVED')} disabled={isSuccessCheck}>
                  <Check size={14} /> Approve & Save
                </button>
                <button className="kyc-btn-reject" onClick={() => handleAction('REJECTED')} disabled={isSuccessCheck}>
                  <XCircle size={14} /> Reject
                </button>
                <button className="kyc-btn-secondary" onClick={() => handleAction('REVIEW_REQUIRED')} disabled={isSuccessCheck}>
                  <SkipForward size={14} /> Skip
                </button>
              </>
            )}

            <button className="kyc-btn-secondary" onClick={handleReprocess} disabled={isReprocessing}>
              <RefreshCw size={13} style={{ animation: isReprocessing ? 'spin 1s linear infinite' : 'none' }} />
              {isReprocessing ? 'Running…' : 'Re-run OCR'}
            </button>

            <div className="kyc-divider" />

            <button className="kyc-close-btn" onClick={onClose} title="Close (Esc)">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* ── Main split ──────────────────────────────────────── */}
        <div className="kyc-split">

          {/* LEFT — document preview */}
          <div className="kyc-left-panel">
            <div className="kyc-doc-tabs">
              {availableTabs.map(tab => (
                <button
                  key={tab.id}
                  className={`kyc-doc-tab ${activeDoc === tab.id ? 'active' : ''}`}
                  onClick={() => setActiveDoc(tab.id)}
                >
                  <FileText size={12} />
                  {tab.label}
                  {tab.doc?.signed_url && <span className="kyc-doc-dot" />}
                </button>
              ))}
            </div>

            <div className="kyc-viewer-wrap">
              {docsLoading ? (
                <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                  <div style={{ width: 28, height: 28, borderRadius: '50%', border: '2.5px solid #e5e7eb', borderTopColor: '#2563eb', animation: 'spin 0.8s linear infinite' }} />
                  <span style={{ fontSize: 13, color: '#6b7280' }}>Loading document…</span>
                </div>
              ) : (
                <ReviewDocumentViewer
                  doc={currentDoc}
                  docType={currentTab?.id}
                  label={currentLabel}
                />
              )}
            </div>
          </div>

          {/* RIGHT — structured verification data */}
          <div className="kyc-right-panel">

            {/* 1. Candidate Summary */}
            <CandidateSummaryHeader user={enriched} />

            {/* 2. Master Verified Profile (Single Source of Truth) */}
            <MasterProfileSection user={enriched} />

            {/* 3. KYC Comparison — STRICT entered vs extracted, read-only evidence */}
            <KYCComparisonSection user={enriched} />

            {/* 4. OCR Insights */}
            <OCRInsightsSection user={enriched} />

            {/* 5. Risk Assessment */}
            <RiskAssessmentSection user={enriched} />

            {/* 6. Audit Timeline */}
            <AuditTimelineSection user={enriched} />

          </div>
        </div>
      </div>
    </div>
  );
}
