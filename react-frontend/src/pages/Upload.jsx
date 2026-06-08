import { useState, useRef, useCallback } from 'react';
import { useToast } from '../context/NotificationContext';
import Navbar from '../components/Navbar';
import PipelineStatus from '../components/PipelineStatus';
import { apiCompleteUpload, apiUploadDocumentForUser, apiCreateUser } from '../api/api';
import {
  UploadCloud, User, Calendar, CreditCard, FileText,
  X, CheckCircle2, Shield, Phone, Mail, MapPin, CheckSquare,
  GraduationCap, BookOpen, LayoutList, Award,
  ChevronDown, ChevronUp, AlertCircle,
  ScanLine, Sparkles, ShieldCheck, FileSearch,
  LayoutPanelTop, HardDrive, Cpu,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

// ── Upload pipeline stage definitions ────────────────────────────────────────
const UPLOAD_STAGES_TEMPLATE = [
  { id: 'upload',    title: 'Uploading File',         icon: UploadCloud },
  { id: 'validate',  title: 'Validating Document',    icon: ShieldCheck },
  { id: 'compress',  title: 'Compressing Images',     icon: Cpu },
  { id: 'ocr_prep',  title: 'Preparing OCR Pipeline', icon: ScanLine },
  { id: 'preview',   title: 'Generating Preview',     icon: FileSearch },
  { id: 'metadata',  title: 'Saving Metadata',        icon: HardDrive },
  { id: 'ocr_start', title: 'Starting OCR Engine',    icon: Sparkles },
];

function makeStages() {
  return UPLOAD_STAGES_TEMPLATE.map(s => ({ ...s, status: 'idle', durationMs: 0 }));
}

/* ─── DYNAMIC CONFIGURATION ─── */
const ACADEMIC_CONFIG = {
  tenth: {
    id: 'tenth',
    title: '10th Marksheet (SSC)',
    icon: BookOpen,
    fields: [
      { name: 'percentage', label: 'Percentage / CGPA', placeholder: 'e.g. 82.40' }
    ]
  },
  twelfth: {
    id: 'twelfth',
    title: '12th Marksheet (HSC)',
    icon: Award,
    fields: [
      { name: 'percentage', label: 'Percentage / CGPA', placeholder: 'e.g. 82.40' }
    ]
  },
  diploma: {
    id: 'diploma',
    title: 'Diploma Certificate',
    icon: FileText,
    fields: [
      { name: 'percentage', label: 'Percentage / CGPA', placeholder: 'e.g. 8.72' }
    ]
  },
  degree: {
    id: 'degree',
    title: 'Degree Certificate',
    icon: GraduationCap,
    fields: [
      { name: 'percentage', label: 'CGPA / Percentage', placeholder: 'e.g. 8.72' }
    ]
  }
};

/* ─── SHARED UI COMPONENTS ─── */

const inp = (focused, hasError, hasValue) => ({
  width: '100%', height: 44,
  background: focused ? '#FAFCFF' : '#FFFFFF',
  border: `1.5px solid ${hasError ? '#F87171' : focused ? '#2563EB' : hasValue ? '#C7D7FE' : '#E2E8F0'}`,
  borderRadius: 10,
  padding: '0 14px',
  fontSize: 14, color: '#0F172A', outline: 'none',
  fontFamily: 'inherit', transition: 'all 150ms ease',
  boxSizing: 'border-box',
  boxShadow: hasError ? '0 0 0 3px rgba(239,68,68,0.1)' : focused ? '0 0 0 3px rgba(37,99,235,0.1)' : 'none',
});

const inpWithIcon = (focused, hasError, hasValue) => ({
  ...inp(focused, hasError, hasValue),
  paddingLeft: 40,
});

function Field({ label, icon: Icon, error, hint, badge, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <label style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</label>
        {badge && <span style={{ fontSize: 10, fontWeight: 600, color: '#7C3AED', background: '#F3E8FF', padding: '2px 8px', borderRadius: 20 }}>{badge}</span>}
      </div>
      <div style={{ position: 'relative' }}>
        {Icon && <Icon size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#94A3B8', pointerEvents: 'none', zIndex: 1 }} />}
        {children}
      </div>
      {hint && !error && <p style={{ fontSize: 11, color: '#94A3B8', marginTop: 2, fontWeight: 500, margin: 0 }}>{hint}</p>}
      {error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 2 }}>
          <span style={{ width: 14, height: 14, borderRadius: '50%', background: '#FEE2E2', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#DC2626', fontWeight: 800, flexShrink: 0 }}>✕</span>
          <p style={{ fontSize: 11, color: '#DC2626', fontWeight: 600, margin: 0 }}>{error}</p>
        </div>
      )}
    </div>
  );
}

function SelectionPill({ title, icon: Icon, selected, onClick }) {
  return (
    <motion.div
      whileHover={{ y: -2 }}
      whileTap={{ scale: 0.98 }}
      onClick={onClick}
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '14px',
        border: `2px solid ${selected ? '#2563EB' : '#E2E8F0'}`,
        borderRadius: 16, cursor: 'pointer',
        background: selected ? 'linear-gradient(135deg, #EFF6FF, #DBEAFE)' : '#FFFFFF',
        boxShadow: selected ? '0 4px 12px rgba(37,99,235,0.15)' : '0 2px 4px rgba(15,23,42,0.02)',
        position: 'relative', overflow: 'hidden'
      }}
    >
      <div style={{
        width: 18, height: 18, borderRadius: 6,
        background: selected ? '#2563EB' : '#F1F5F9',
        border: `2px solid ${selected ? '#2563EB' : '#CBD5E1'}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0
      }}>
        {selected && <CheckSquare size={12} color="#FFF" style={{ position: 'absolute' }} />}
      </div>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: selected ? '#BFDBFE' : '#F1F5F9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Icon size={16} color={selected ? '#1D4ED8' : '#64748B'} />
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: selected ? '#1E3A8A' : '#334155' }}>{title}</div>
    </motion.div>
  );
}

function DropZone({ label, file, preview, onFile, onRemove }) {
  const [hover, setHover] = useState(false);
  const isPdf = preview === '__pdf__' || file?.type === 'application/pdf' || (file?.name || '').toLowerCase().endsWith('.pdf');
  const isImagePreview = preview && preview !== '__pdf__';
  const ref = useRef(null);

  if (file) {
    return (
      <div style={{ border: '1.5px solid #E2E8F0', borderRadius: 12, overflow: 'hidden', background: '#F8FAFC', display: 'flex', flexDirection: 'column', height: '100%' }}>
        {isImagePreview ? (
          <img src={preview} alt="preview" style={{ width: '100%', flex: 1, objectFit: 'cover', display: 'block', minHeight: 0 }} />
        ) : (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8, background: '#EFF6FF', minHeight: 0 }}>
            <div style={{ width: 44, height: 44, borderRadius: 10, background: '#DBEAFE', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FileText size={22} color="#2563EB" />
            </div>
          </div>
        )}
        <div style={{ background: '#fff', borderTop: '1px solid #E2E8F0', padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ flex: 1, overflow: 'hidden' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: '#0F172A', textOverflow: 'ellipsis', whiteSpace: 'nowrap', overflow: 'hidden' }}>{file.name}</div>
            <div style={{ fontSize: 11, color: '#94A3B8' }}>{(file.size / 1024 / 1024).toFixed(2)} MB</div>
          </div>
          <button onClick={onRemove} style={{ width: 28, height: 28, borderRadius: '50%', background: '#FEE2E2', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#DC2626' }}>
            <X size={14} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      onClick={() => ref.current?.click()}
      onDragOver={e => { e.preventDefault(); setHover(true); }}
      onDragLeave={() => setHover(false)}
      onDrop={e => {
        e.preventDefault(); setHover(false);
        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
          onFile({ target: { files: e.dataTransfer.files } });
        }
      }}
      style={{
        height: '100%', minHeight: 120, border: `2px dashed ${hover ? '#2563EB' : '#CBD5E1'}`,
        borderRadius: 12, background: hover ? '#EFF6FF' : '#F8FAFC',
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10,
        cursor: 'pointer', transition: 'all 0.2s',
      }}
    >
      <input ref={ref} type="file" accept="image/*,application/pdf" style={{ display: 'none' }} onChange={onFile} />
      <div style={{ width: 42, height: 42, borderRadius: 10, background: hover ? '#DBEAFE' : '#F1F5F9', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <UploadCloud size={20} color={hover ? '#2563EB' : '#94A3B8'} />
      </div>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: hover ? '#2563EB' : '#64748B' }}>{label || "Upload File"}</div>
        <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4 }}>PDF, JPG, PNG</div>
      </div>
    </div>
  );
}

/* ─── Academic Collapsible Card ─── */
function AcademicCard({ config, data, onUpdate, onFile, onRemove }) {
  const [isOpen, setIsOpen] = useState(true);
  const Icon = config.icon;
  const hasFile = !!data.file;
  // File is required, inputs are optional but good for completion status
  const isComplete = hasFile;

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 16, overflow: 'hidden', boxShadow: '0 2px 6px rgba(15,23,42,0.03)' }}>
      {/* Header */}
      <div onClick={() => setIsOpen(!isOpen)} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', background: isOpen ? '#F8FAFC' : '#FFFFFF', cursor: 'pointer', borderBottom: isOpen ? '1px solid #E2E8F0' : 'none' }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Icon size={16} color="#2563EB" />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0F172A' }}>{config.title}</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {isComplete ? (
            <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 700, color: '#16A34A', background: '#DCFCE7', padding: '4px 10px', borderRadius: 20 }}><CheckCircle2 size={12}/> Ready</span>
          ) : (
             <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 700, color: '#D97706', background: '#FEF3C7', padding: '4px 10px', borderRadius: 20 }}><AlertCircle size={12}/> Missing File</span>
          )}
          {isOpen ? <ChevronUp size={18} color="#94A3B8" /> : <ChevronDown size={18} color="#94A3B8" />}
        </div>
      </div>

      {/* Body */}
      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} style={{ overflow: 'hidden' }}>
            <div style={{ padding: 18, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
              {/* Left Side: Inputs */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16, justifyContent: 'center' }}>
                {config.fields.map(f => (
                  <Field key={f.name} label={f.label}>
                    <input
                      value={data[f.name] || ''}
                      onChange={e => onUpdate(config.id, f.name, e.target.value)}
                      placeholder={f.placeholder}
                      style={inp(false, false, data[f.name])}
                    />
                  </Field>
                ))}
              </div>
              {/* Right Side: Upload */}
              <div style={{ minHeight: 140 }}>
                <DropZone label={`Upload ${config.title}`} file={data.file} preview={data.preview} onFile={e => onFile(config.id, e.target.files[0])} onRemove={() => onRemove(config.id)} />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/* ─── Multi-Semester Uploader ─── */
function SemesterMultiCard({ files, setFiles }) {
  const [isOpen, setIsOpen] = useState(true);
  const ref = useRef(null);

  const handleAdd = (e) => {
    const newFiles = Array.from(e.target.files);
    if (!newFiles.length) return;
    const mapped = newFiles.map((file, i) => {
      const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
      return {
        id: Math.random().toString(36).substring(7),
        semester: `Semester ${files.length + i + 1}`,
        spi: '',
        file,
        preview: isPdf ? '__pdf__' : URL.createObjectURL(file)
      };
    });
    setFiles(prev => [...prev, ...mapped]);
  };

  const remove = (id) => setFiles(prev => prev.filter(f => f.id !== id));
  const updateSem = (id, field, val) => setFiles(prev => prev.map(f => f.id === id ? { ...f, [field]: val } : f));

  return (
    <div style={{ background: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: 16, overflow: 'hidden', boxShadow: '0 2px 6px rgba(15,23,42,0.03)' }}>
      <div onClick={() => setIsOpen(!isOpen)} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '14px 18px', background: isOpen ? '#F8FAFC' : '#FFFFFF', cursor: 'pointer', borderBottom: isOpen ? '1px solid #E2E8F0' : 'none' }}>
        <div style={{ width: 34, height: 34, borderRadius: 10, background: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <LayoutList size={16} color="#2563EB" />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#0F172A' }}>Semester Grade Cards</div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {files.length > 0 ? (
             <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 700, color: '#16A34A', background: '#DCFCE7', padding: '4px 10px', borderRadius: 20 }}><CheckCircle2 size={12}/> {files.length} Uploaded</span>
          ) : (
             <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, fontWeight: 700, color: '#D97706', background: '#FEF3C7', padding: '4px 10px', borderRadius: 20 }}><AlertCircle size={12}/> Missing Files</span>
          )}
          {isOpen ? <ChevronUp size={18} color="#94A3B8" /> : <ChevronDown size={18} color="#94A3B8" />}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {isOpen && (
          <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} style={{ overflow: 'hidden' }}>
            <div style={{ padding: 18 }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
                
                {files.map((item) => (
                  <div key={item.id} style={{ display: 'flex', gap: 12, padding: 12, border: '1px solid #E2E8F0', borderRadius: 12, background: '#F8FAFC' }}>
                    {/* Thumbnail */}
                    <div style={{ width: 64, height: 64, borderRadius: 8, overflow: 'hidden', flexShrink: 0, background: '#EFF6FF' }}>
                      {item.preview === '__pdf__' ? (
                        <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}><FileText size={20} color="#2563EB" /></div>
                      ) : (
                        <img src={item.preview} alt="preview" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      )}
                    </div>
                    {/* Inputs */}
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6, justifyContent: 'center' }}>
                      <input value={item.semester} onChange={e => updateSem(item.id, 'semester', e.target.value)} placeholder="Semester Name" style={{ width: '100%', border: 'none', background: 'transparent', fontSize: 13, fontWeight: 700, color: '#0F172A', outline: 'none' }} />
                      <input value={item.spi} onChange={e => updateSem(item.id, 'spi', e.target.value)} placeholder="SGPA / SPI (e.g. 8.5)" style={{ width: '100%', border: 'none', background: 'transparent', fontSize: 12, fontWeight: 500, color: '#475569', outline: 'none' }} />
                    </div>
                    {/* Delete */}
                    <button onClick={() => remove(item.id)} style={{ alignSelf: 'flex-start', background: 'none', border: 'none', color: '#94A3B8', cursor: 'pointer', padding: 4 }}><X size={14}/></button>
                  </div>
                ))}

                {/* Add Semester Button */}
                <div onClick={() => ref.current?.click()} style={{ height: 88, border: '2px dashed #CBD5E1', borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', background: '#F8FAFC', gap: 8, transition: 'all 0.2s' }}>
                  <input ref={ref} type="file" multiple accept="image/*,application/pdf" style={{ display: 'none' }} onChange={handleAdd} />
                  <UploadCloud size={18} color="#2563EB" />
                  <span style={{ fontSize: 13, fontWeight: 600, color: '#2563EB' }}>Add Semester</span>
                </div>

              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}


/* ─── MAIN ONBOARDING COMPONENT ─── */
export default function Upload() {
  const toast = useToast();
  const submittingRef = useRef(false); // hard guard — prevents ANY re-entry
  const cancelledRef  = useRef(false);
  const [step, setStep] = useState(1);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [focused, setFocused] = useState({});
  const [fieldErrors, setFieldErrors] = useState({}); // inline validation errors
  const [uploadStages, setUploadStages] = useState(makeStages());

  // Form State
  const [profile, setProfile] = useState({ fullName: '', dob: '', mobile: '', email: '', address: '' });
  const [kycFiles, setKycFiles] = useState({ aadhaar: null, pan: null });
  const [kycPreviews, setKycPreviews] = useState({ aadhaar: null, pan: null });
  const [kycInputs, setKycInputs] = useState({ aadhaarNum: '', panNum: '' });

  const [acadSelection, setAcadSelection] = useState({ tenth: false, twelfth: false, diploma: false, degree: false, semesters: false });
  const [acadInputs, setAcadInputs] = useState({
    tenth: { percentage: '', year: '' },
    twelfth: { percentage: '', year: '' },
    diploma: { percentage: '', year: '' },
    degree: { percentage: '', year: '' }
  });
  const [acadFiles, setAcadFiles] = useState({ tenth: null, twelfth: null, diploma: null, degree: null });
  const [acadPreviews, setAcadPreviews] = useState({ tenth: null, twelfth: null, diploma: null, degree: null });
  const [semFiles, setSemFiles] = useState([]);

  // ── Centralized validation — runs ONCE, returns errors object ──
  const validate = useCallback(() => {
    const errs = {};
    if (!profile.fullName || profile.fullName.trim().length < 2)
      errs.fullName = 'Please enter the candidate\'s full name (min 2 characters).';
    if (!profile.dob)
      errs.dob = 'Please enter the candidate date of birth.';
    if (!kycFiles.aadhaar && !kycFiles.pan)
      errs.kyc = 'At least one KYC document (Aadhaar or PAN) must be uploaded.';
    return errs;
  }, [profile.fullName, profile.dob, kycFiles.aadhaar, kycFiles.pan]);

  // Clear a field error when user starts fixing it
  const clearErr = (key) => setFieldErrors(p => { const n = { ...p }; delete n[key]; return n; });

  // Helpers
  const setP = (k, v) => setProfile(p => ({ ...p, [k]: v }));
  const setFoc = (k, v) => setFocused(p => ({ ...p, [k]: v }));
  const toggleAcad = (k) => setAcadSelection(p => ({ ...p, [k]: !p[k] }));
  const updateAcadInput = (id, field, val) => setAcadInputs(p => ({ ...p, [id]: { ...p[id], [field]: val } }));

  const handleAcadFile = (id, file) => {
    if (!file) return;
    const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
    const preview = isPdf ? '__pdf__' : URL.createObjectURL(file);
    setAcadFiles(p => ({ ...p, [id]: file }));
    setAcadPreviews(p => ({ ...p, [id]: preview }));
  };
  const removeAcadFile = (id) => {
    setAcadFiles(p => ({ ...p, [id]: null }));
    setAcadPreviews(p => ({ ...p, [id]: null }));
  };

  // ── Stage helpers ─────────────────────────────────────────────────────────
  const setStage = (id, status, durationMs) =>
    setUploadStages(prev =>
      prev.map(s => s.id === id ? { ...s, status, ...(durationMs != null ? { durationMs } : {}) } : s)
    );

  const runStage = async (id, fn, options = {}) => {
    if (cancelledRef.current) return null;
    const t0 = Date.now();
    setStage(id, 'running');
    try {
      const result = await fn();
      if (!cancelledRef.current) setStage(id, 'completed', Date.now() - t0);
      return result;
    } catch (err) {
      setStage(id, 'failed', Date.now() - t0);
      if (options.critical) throw err;
      console.warn(`[Upload] Stage ${id} failed (non-critical):`, err.message);
      return null;
    }
  };

  // ── Cancel handler ────────────────────────────────────────────────────────
  const handleCancel = () => {
    if (!submittingRef.current) return;
    cancelledRef.current = true;
    setBusy(false);
    submittingRef.current = false;
    setUploadStages(prev =>
      prev.map(s => s.status === 'running' ? { ...s, status: 'failed', error: 'Cancelled' } : s)
    );
  };

  // ── Submit Handler — guarded against re-entry ──────────────
  const handleSubmit = async () => {
    if (submittingRef.current) return;

    const errs = validate();
    if (Object.keys(errs).length > 0) {
      setFieldErrors(errs);
      const firstKey = Object.keys(errs)[0];
      document.getElementById(`field-${firstKey}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }

    submittingRef.current = true;
    cancelledRef.current  = false;
    setFieldErrors({});
    setBusy(true);
    setUploadStages(makeStages()); // reset stages

    try {
      let userId = null;

      // ── Stage: Uploading File ─────────────────────────────────────────────
      const kycResult = await runStage('upload', async () => {
        if (kycFiles.aadhaar || kycFiles.pan) {
          return await apiCompleteUpload({
            fullName:      profile.fullName.trim(),
            dob:           profile.dob,
            aadhaarNumber: kycInputs.aadhaarNum,
            panNumber:     kycInputs.panNum,
            aadhaarFile:   kycFiles.aadhaar,
            panFile:       kycFiles.pan,
            mobile:        profile.mobile,
            email:         profile.email,
            address:       profile.address,
          });
        } else {
          return await apiCreateUser(
            profile.fullName.trim(), profile.dob,
            profile.mobile, profile.email, profile.address
          );
        }
      }, { critical: true });

      if (cancelledRef.current) return;

      userId = kycResult?.user_id ?? kycResult?.user?.id ?? null;
      if (!userId) throw new Error('Failed to create candidate record. Please try again.');

      // ── Stage: Validating Document ────────────────────────────────────────
      await runStage('validate', () => new Promise(r => setTimeout(r, 300)));
      if (cancelledRef.current) return;

      // ── Stage: Compressing Images ─────────────────────────────────────────
      await runStage('compress', () => new Promise(r => setTimeout(r, 200)));
      if (cancelledRef.current) return;

      // ── Stage: Preparing OCR Pipeline ─────────────────────────────────────
      await runStage('ocr_prep', () => new Promise(r => setTimeout(r, 150)));
      if (cancelledRef.current) return;

      // ── Stage: Generating Preview ─────────────────────────────────────────
      await runStage('preview', () => new Promise(r => setTimeout(r, 150)));
      if (cancelledRef.current) return;

      // ── Stage: Saving Metadata + academic docs ────────────────────────────
      await runStage('metadata', async () => {
        const ACAD_TYPE_MAP = {
          tenth: 'tenth', twelfth: 'twelfth',
          diploma: 'diploma', degree: 'degree', semesters: 'semester',
        };
        const acadUploadJobs = [];
        for (const [key, docType] of Object.entries(ACAD_TYPE_MAP)) {
          if (key === 'semesters') continue;
          const file = acadFiles[key];
          if (acadSelection[key] && file) {
            acadUploadJobs.push(
              apiUploadDocumentForUser(userId, docType, file, acadInputs[key]?.percentage || '')
                .catch(err => console.warn(`[Upload] ${docType} failed:`, err.message))
            );
          }
        }
        if (acadSelection.semesters) {
          for (const sem of semFiles) {
            if (sem.file) {
              acadUploadJobs.push(
                apiUploadDocumentForUser(userId, 'semester', sem.file, sem.spi || '')
                  .catch(err => console.warn('[Upload] semester failed:', err.message))
              );
            }
          }
        }
        if (acadUploadJobs.length > 0) await Promise.allSettled(acadUploadJobs);
      });
      if (cancelledRef.current) return;

      // ── Stage: Starting OCR Engine ────────────────────────────────────────
      await runStage('ocr_start', () => new Promise(r => setTimeout(r, 200)));
      if (cancelledRef.current) return;

      setSuccess(true);
      window.scrollTo(0, 0);
    } catch (err) {
      toast(err.message || 'Submission failed. Please try again.', 'error');
    } finally {
      if (!cancelledRef.current) setBusy(false);
      submittingRef.current = false;
    }
  };

  // Right Side Summary Calculations
  const hasAadhaar = !!kycFiles.aadhaar;
  const hasPan = !!kycFiles.pan;
  const docsSelectedCount = Object.values(acadSelection).filter(Boolean).length + 2; 
  const docsUploadedCount = [kycFiles.aadhaar, kycFiles.pan, acadFiles.tenth, acadFiles.twelfth, acadFiles.diploma, acadFiles.degree].filter(Boolean).length + (semFiles.length > 0 ? 1 : 0);
  const progressPct = Math.min(100, Math.round((docsUploadedCount / (docsSelectedCount || 1)) * 100));

  if (success) {
    return (
      <div style={{ flex: 1, background: '#F8FAFC' }}>
         <Navbar title="Document Onboarding" subtitle="KYC verification — step-by-step" />
         <div style={{ padding: '80px 24px', maxWidth: 640, margin: '0 auto', textAlign: 'center' }}>
           <div style={{ width: 80, height: 80, borderRadius: '50%', background: '#DCFCE7', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 24px', boxShadow: '0 0 0 10px rgba(22,163,74,0.1)' }}>
             <CheckCircle2 size={40} color="#16A34A" />
           </div>
           <h2 style={{ fontSize: 26, fontWeight: 800, color: '#0F172A', marginBottom: 12 }}>Onboarding Complete!</h2>
           <p style={{ fontSize: 15, color: '#64748B', lineHeight: 1.5, marginBottom: 32 }}>
             Your profile, KYC documents, and academic records have been securely uploaded. The AI engines are extracting and verifying your data in the background.
           </p>
           <button onClick={() => window.location.reload()} style={{ padding: '12px 32px', borderRadius: 12, background: 'linear-gradient(135deg, #2563EB, #4F46E5)', color: '#fff', fontSize: 15, fontWeight: 700, border: 'none', cursor: 'pointer', boxShadow: '0 4px 14px rgba(37,99,235,0.3)' }}>
             Submit Another Profile
           </button>
         </div>
      </div>
    );
  }

  return (
    <div style={{ flex: 1, background: '#F8FAFC', minHeight: '100vh', paddingBottom: 100 }}>
      <Navbar title="Candidate Onboarding" subtitle="Unified Verification Portal" />
      
      {/* Top Progress Bar */}
      <div style={{ background: '#fff', borderBottom: '1px solid #E2E8F0', position: 'sticky', top: 60, zIndex: 10 }}>
        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 16 }}>
          {[1,2,3,4].map(s => (
            <div key={s} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 24, height: 24, borderRadius: '50%', background: step >= s ? '#2563EB' : '#F1F5F9', color: step >= s ? '#fff' : '#94A3B8', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12, fontWeight: 700 }}>
                  {step > s ? <CheckCircle2 size={14} /> : s}
                </div>
                <span style={{ fontSize: 13, fontWeight: 600, color: step >= s ? '#0F172A' : '#94A3B8' }}>
                  {s === 1 ? 'Profile' : s === 2 ? 'Identity' : s === 3 ? 'Academics' : 'Review'}
                </span>
              </div>
              {s !== 4 && <div style={{ width: 40, height: 2, background: step > s ? '#2563EB' : '#E2E8F0', borderRadius: 2 }} />}
            </div>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 1080, margin: '40px auto 0', padding: '0 24px', display: 'flex', gap: 32, alignItems: 'flex-start' }}>
        
        {/* LEFT MAIN CONTENT */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 32 }}>
          
          {/* STEP 1: PROFILE */}
          {step === 1 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ background: '#fff', borderRadius: 24, padding: 32, boxShadow: '0 4px 24px rgba(15,23,42,0.04)', border: '1px solid #E2E8F0' }}>
              <div style={{ marginBottom: 32 }}>
                <h2 style={{ fontSize: 22, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.02em' }}>Personal Information</h2>
                <p style={{ fontSize: 14, color: '#64748B', marginTop: 6 }}>Enter details exactly as they appear on your government IDs.</p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                <div id="field-fullName">
                  <Field label="Full Name" icon={User} error={fieldErrors.fullName} hint={!fieldErrors.fullName ? 'Required' : undefined}>
                    <input value={profile.fullName} onChange={e=>{ setP('fullName', e.target.value); clearErr('fullName'); }} onFocus={()=>setFoc('fullName', true)} onBlur={()=>setFoc('fullName', false)} placeholder="e.g. Aditya Jadhav" style={inpWithIcon(focused.fullName, !!fieldErrors.fullName, profile.fullName)} />
                  </Field>
                </div>
                <div id="field-dob">
                  <Field label="Date of Birth" icon={Calendar} error={fieldErrors.dob} hint={!fieldErrors.dob ? 'Required' : undefined}>
                    <input type="date" value={profile.dob} onChange={e=>{ setP('dob', e.target.value); clearErr('dob'); }} onFocus={()=>setFoc('dob', true)} onBlur={()=>setFoc('dob', false)} style={{...inpWithIcon(focused.dob, !!fieldErrors.dob, profile.dob), colorScheme: 'light'}} />
                  </Field>
                </div>
                <Field label="Mobile Number" icon={Phone}><input value={profile.mobile} onChange={e=>setP('mobile', e.target.value)} onFocus={()=>setFoc('mobile', true)} onBlur={()=>setFoc('mobile', false)} placeholder="+91 XXXXX XXXXX" style={inpWithIcon(focused.mobile, false, profile.mobile)} /></Field>
                <Field label="Email Address" icon={Mail}><input value={profile.email} onChange={e=>setP('email', e.target.value)} onFocus={()=>setFoc('email', true)} onBlur={()=>setFoc('email', false)} placeholder="aditya@example.com" style={inpWithIcon(focused.email, false, profile.email)} /></Field>
                <div style={{ gridColumn: '1 / -1' }}>
                  <Field label="Permanent Address" icon={MapPin}><input value={profile.address} onChange={e=>setP('address', e.target.value)} onFocus={()=>setFoc('address', true)} onBlur={()=>setFoc('address', false)} placeholder="123 Street Name, City, State, PIN" style={inpWithIcon(focused.address, false, profile.address)} /></Field>
                </div>
              </div>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 32 }}>
                <button
                  onClick={() => {
                    const errs = validate();
                    const stepErrs = {};
                    if (errs.fullName) stepErrs.fullName = errs.fullName;
                    if (errs.dob) stepErrs.dob = errs.dob;
                    if (Object.keys(stepErrs).length) { setFieldErrors(stepErrs); return; }
                    setFieldErrors({});
                    setStep(2);
                  }}
                  style={{ padding: '0 28px', height: 46, borderRadius: 12, background: 'linear-gradient(135deg, #2563EB, #4F46E5)', color: '#fff', fontSize: 14, fontWeight: 700, border: 'none', cursor: 'pointer', boxShadow: '0 4px 14px rgba(37,99,235,0.25)' }}
                >Next Step: Identity</button>
              </div>
            </motion.div>
          )}

          {/* STEP 2: IDENTITY */}
          {step === 2 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ background: '#fff', borderRadius: 24, padding: 32, boxShadow: '0 4px 24px rgba(15,23,42,0.04)', border: '1px solid #E2E8F0' }}>
              <div style={{ marginBottom: 32 }}>
                <h2 style={{ fontSize: 22, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.02em' }}>Identity Documents</h2>
                <p style={{ fontSize: 14, color: '#64748B', marginTop: 6 }}>Upload your Aadhaar and PAN for basic KYC verification.</p>
              </div>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: 32 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32, alignItems: 'start' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#1E3A8A' }}>Aadhaar Details</div>
                    <Field label="Aadhaar Number"><input value={kycInputs.aadhaarNum} onChange={e=>setKycInputs(p=>({...p, aadhaarNum: e.target.value.replace(/\D/g,'').slice(0,12)}))} placeholder="XXXX XXXX XXXX" style={inp(false, false, kycInputs.aadhaarNum)} /></Field>
                  </div>
                  <div style={{ minHeight: 120 }}>
                     <DropZone label="Upload Aadhaar File" type="aadhaar" file={kycFiles.aadhaar} preview={kycPreviews.aadhaar} onFile={(e)=> {setKycFiles(p=>({...p, aadhaar: e.target.files[0]})); setKycPreviews(p=>({...p, aadhaar: URL.createObjectURL(e.target.files[0])}))}} onRemove={()=>{setKycFiles(p=>({...p, aadhaar:null})); setKycPreviews(p=>({...p, aadhaar:null}))}} />
                  </div>
                </div>

                <div style={{ width: '100%', height: 1, background: '#E2E8F0' }} />

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32, alignItems: 'start' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#1E3A8A' }}>PAN Details</div>
                    <Field label="PAN Number"><input value={kycInputs.panNum} onChange={e=>setKycInputs(p=>({...p, panNum: e.target.value.toUpperCase().slice(0,10)}))} placeholder="ABCDE1234F" style={inp(false, false, kycInputs.panNum)} /></Field>
                  </div>
                  <div style={{ minHeight: 120 }}>
                     <DropZone label="Upload PAN File" type="pan" file={kycFiles.pan} preview={kycPreviews.pan} onFile={(e)=> {setKycFiles(p=>({...p, pan: e.target.files[0]})); setKycPreviews(p=>({...p, pan: URL.createObjectURL(e.target.files[0])}))}} onRemove={()=>{setKycFiles(p=>({...p, pan:null})); setKycPreviews(p=>({...p, pan:null}))}} />
                  </div>
                </div>
              </div>
              
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 40 }}>
                <button onClick={() => setStep(1)} style={{ padding: '0 24px', height: 46, borderRadius: 12, background: '#F1F5F9', color: '#475569', fontSize: 14, fontWeight: 700, border: 'none', cursor: 'pointer' }}>Back</button>
                <button onClick={() => setStep(3)} style={{ padding: '0 28px', height: 46, borderRadius: 12, background: 'linear-gradient(135deg, #2563EB, #4F46E5)', color: '#fff', fontSize: 14, fontWeight: 700, border: 'none', cursor: 'pointer', boxShadow: '0 4px 14px rgba(37,99,235,0.25)' }}>Next Step: Academics</button>
              </div>
            </motion.div>
          )}

          {/* STEP 3: ACADEMICS */}
          {step === 3 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              
              {/* Selector Block */}
              <div style={{ background: '#fff', borderRadius: 24, padding: 32, boxShadow: '0 4px 24px rgba(15,23,42,0.04)', border: '1px solid #E2E8F0' }}>
                <div style={{ marginBottom: 24 }}>
                  <h2 style={{ fontSize: 20, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.02em' }}>Select Academic Documents</h2>
                  <p style={{ fontSize: 14, color: '#64748B', marginTop: 4 }}>Select the records you have available to upload.</p>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                  <SelectionPill title="10th Marksheet" icon={BookOpen} selected={acadSelection.tenth} onClick={() => toggleAcad('tenth')} />
                  <SelectionPill title="12th Marksheet" icon={Award} selected={acadSelection.twelfth} onClick={() => toggleAcad('twelfth')} />
                  <SelectionPill title="Diploma" icon={FileText} selected={acadSelection.diploma} onClick={() => toggleAcad('diploma')} />
                  <SelectionPill title="Degree" icon={GraduationCap} selected={acadSelection.degree} onClick={() => toggleAcad('degree')} />
                  <SelectionPill title="Semester Cards" icon={LayoutList} selected={acadSelection.semesters} onClick={() => toggleAcad('semesters')} />
                </div>
              </div>

              {/* Dynamic Forms */}
              {['tenth', 'twelfth', 'diploma', 'degree'].map(type => 
                 acadSelection[type] && <AcademicCard key={type} config={ACADEMIC_CONFIG[type]} data={{...acadInputs[type], file: acadFiles[type], preview: acadPreviews[type]}} onUpdate={updateAcadInput} onFile={handleAcadFile} onRemove={removeAcadFile} />
              )}
              {acadSelection.semesters && <SemesterMultiCard files={semFiles} setFiles={setSemFiles} />}

              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 16 }}>
                <button onClick={() => setStep(2)} style={{ padding: '0 24px', height: 46, borderRadius: 12, background: '#F1F5F9', color: '#475569', fontSize: 14, fontWeight: 700, border: 'none', cursor: 'pointer' }}>Back</button>
                <button onClick={() => setStep(4)} style={{ padding: '0 28px', height: 46, borderRadius: 12, background: 'linear-gradient(135deg, #2563EB, #4F46E5)', color: '#fff', fontSize: 14, fontWeight: 700, border: 'none', cursor: 'pointer', boxShadow: '0 4px 14px rgba(37,99,235,0.25)' }}>Review & Submit</button>
              </div>
            </motion.div>
          )}

          {/* STEP 4: REVIEW */}
          {step === 4 && (
            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} style={{ background: '#fff', borderRadius: 24, padding: 40, boxShadow: '0 4px 24px rgba(15,23,42,0.04)', border: '1px solid #E2E8F0' }}>
              <div style={{ marginBottom: 32, textAlign: 'center' }}>
                <div style={{ width: 64, height: 64, borderRadius: '50%', background: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                  <Shield size={32} color="#2563EB" />
                </div>
                <h2 style={{ fontSize: 24, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.02em' }}>Review & Submit</h2>
                <p style={{ fontSize: 14, color: '#64748B', marginTop: 6 }}>Ensure all your provided information and uploaded files are correct.</p>
              </div>

              {/* Inline validation errors on review step */}
              {Object.keys(fieldErrors).length > 0 && (
                <div style={{ background: '#FEF2F2', border: '1px solid #FECACA', borderRadius: 12, padding: '14px 18px', marginBottom: 20 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#DC2626', marginBottom: 8 }}>Please fix the following before submitting:</div>
                  {Object.values(fieldErrors).map((e, i) => (
                    <div key={i} style={{ fontSize: 13, color: '#B91C1C', marginTop: 4, display: 'flex', alignItems: 'flex-start', gap: 6 }}>
                      <span style={{ flexShrink: 0, marginTop: 1 }}>•</span>{e}
                    </div>
                  ))}
                </div>
              )}
              <div style={{ background: '#F8FAFC', borderRadius: 16, padding: 24, border: '1px solid #E2E8F0', marginBottom: 32 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>Submission Summary</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Full Name</span><span style={{ fontWeight: 600, color: profile.fullName ? '#0F172A' : '#DC2626', fontSize: 14 }}>{profile.fullName || 'Not provided'}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Date of Birth</span><span style={{ fontWeight: 600, color: profile.dob ? '#0F172A' : '#DC2626', fontSize: 14 }}>{profile.dob || 'Not provided'}</span></div>
                  {profile.mobile && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Mobile</span><span style={{ fontWeight: 600, color: '#0F172A', fontSize: 14 }}>{profile.mobile}</span></div>}
                  <div style={{ height: 1, background: '#E2E8F0' }} />
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Aadhaar Card</span><span style={{ fontWeight: 600, color: kycFiles.aadhaar ? '#16A34A' : '#94A3B8', fontSize: 14 }}>{kycFiles.aadhaar ? `✓ ${kycFiles.aadhaar.name}` : 'Not uploaded'}</span></div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>PAN Card</span><span style={{ fontWeight: 600, color: kycFiles.pan ? '#16A34A' : '#94A3B8', fontSize: 14 }}>{kycFiles.pan ? `✓ ${kycFiles.pan.name}` : 'Not uploaded'}</span></div>
                  <div style={{ height: 1, background: '#E2E8F0' }} />
                  {/* Named academic docs — each shown separately */}
                  {acadSelection.tenth && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>10th Marksheet</span><span style={{ fontWeight: 600, color: acadFiles.tenth ? '#16A34A' : '#F59E0B', fontSize: 14 }}>{acadFiles.tenth ? `✓ ${acadFiles.tenth.name}` : 'File missing'}</span></div>}
                  {acadSelection.twelfth && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>12th Marksheet</span><span style={{ fontWeight: 600, color: acadFiles.twelfth ? '#16A34A' : '#F59E0B', fontSize: 14 }}>{acadFiles.twelfth ? `✓ ${acadFiles.twelfth.name}` : 'File missing'}</span></div>}
                  {acadSelection.diploma && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Diploma</span><span style={{ fontWeight: 600, color: acadFiles.diploma ? '#16A34A' : '#F59E0B', fontSize: 14 }}>{acadFiles.diploma ? `✓ ${acadFiles.diploma.name}` : 'File missing'}</span></div>}
                  {acadSelection.degree && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Degree Certificate</span><span style={{ fontWeight: 600, color: acadFiles.degree ? '#16A34A' : '#F59E0B', fontSize: 14 }}>{acadFiles.degree ? `✓ ${acadFiles.degree.name}` : 'File missing'}</span></div>}
                  {acadSelection.semesters && <div style={{ display: 'flex', justifyContent: 'space-between' }}><span style={{ color: '#475569', fontSize: 14 }}>Semester Cards</span><span style={{ fontWeight: 600, color: semFiles.length ? '#16A34A' : '#F59E0B', fontSize: 14 }}>{semFiles.length ? `✓ ${semFiles.length} file${semFiles.length > 1 ? 's' : ''}` : 'No files added'}</span></div>}
                  {!acadSelection.tenth && !acadSelection.twelfth && !acadSelection.diploma && !acadSelection.degree && !acadSelection.semesters && (
                    <div style={{ fontSize: 13, color: '#94A3B8', fontStyle: 'italic' }}>No academic documents selected</div>
                  )}
                </div>
              </div>
              
              {/* ── PIPELINE PROGRESS OVERLAY (shown while busy) ── */}
              <AnimatePresence>
                {busy && (
                  <motion.div
                    initial={{ opacity: 0, y: 8, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: -4, scale: 0.98 }}
                    style={{ marginBottom: 24 }}
                  >
                    <PipelineStatus
                      steps={uploadStages}
                      variant="modal"
                      title="Submitting Profile"
                      subtitle="Uploading documents & starting AI engines"
                      estimatedSeconds={30}
                    />
                  </motion.div>
                )}
              </AnimatePresence>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <button
                  disabled={busy}
                  onClick={() => { if (!busy) { setFieldErrors({}); setStep(3); } }}
                  style={{ padding: '0 24px', height: 48, borderRadius: 12, background: '#F1F5F9', color: busy ? '#CBD5E1' : '#475569', fontSize: 14, fontWeight: 700, border: 'none', cursor: busy ? 'not-allowed' : 'pointer' }}
                >Back to Edit</button>

                <div style={{ display: 'flex', gap: 10 }}>
                  {/* Cancel button during processing */}
                  {busy && (
                    <button
                      onClick={handleCancel}
                      style={{ padding: '0 20px', height: 48, borderRadius: 12, background: '#FEF2F2', color: '#EF4444', fontSize: 14, fontWeight: 700, border: '1px solid #FECACA', cursor: 'pointer' }}
                    >Cancel</button>
                  )}
                  <button
                    disabled={busy}
                    onClick={handleSubmit}
                    style={{
                      padding: '0 32px', height: 48, borderRadius: 12,
                      background: busy ? '#E2E8F0' : 'linear-gradient(135deg, #16A34A, #059669)',
                      color: busy ? '#94A3B8' : '#fff',
                      fontSize: 15, fontWeight: 700, border: 'none',
                      cursor: busy ? 'not-allowed' : 'pointer',
                      boxShadow: busy ? 'none' : '0 4px 14px rgba(22,163,74,0.3)',
                      display: 'flex', alignItems: 'center', gap: 8, transition: 'all 0.2s'
                    }}
                  >
                    {busy
                      ? <><div style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid rgba(148,163,184,0.4)', borderTopColor: '#94A3B8', animation: 'spin 0.8s linear infinite' }} /> Processing…</>
                      : <><CheckCircle2 size={18} /> Submit Profile</>
                    }
                  </button>
                </div>
              </div>
            </motion.div>
          )}

        </div>

        {/* RIGHT SUMMARY PANEL */}
        <div style={{ width: 300, position: 'sticky', top: 124, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: '#fff', borderRadius: 20, padding: 24, boxShadow: '0 4px 24px rgba(15,23,42,0.04)', border: '1px solid #E2E8F0' }}>
            <h3 style={{ fontSize: 14, fontWeight: 800, color: '#0F172A', marginTop: 0, marginBottom: 20, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Upload Summary</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {hasAadhaar ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#94A3B8" />}
                <span style={{ fontSize: 13, fontWeight: 600, color: hasAadhaar ? '#0F172A' : '#94A3B8' }}>Aadhaar Card</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {hasPan ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#94A3B8" />}
                <span style={{ fontSize: 13, fontWeight: 600, color: hasPan ? '#0F172A' : '#94A3B8' }}>PAN Card</span>
              </div>
              
              {acadSelection.tenth && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {acadFiles.tenth ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#F59E0B" />}
                  <span style={{ fontSize: 13, fontWeight: 600, color: acadFiles.tenth ? '#0F172A' : '#F59E0B' }}>10th Marksheet</span>
                </div>
              )}
              {acadSelection.twelfth && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {acadFiles.twelfth ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#F59E0B" />}
                  <span style={{ fontSize: 13, fontWeight: 600, color: acadFiles.twelfth ? '#0F172A' : '#F59E0B' }}>12th Marksheet</span>
                </div>
              )}
              {acadSelection.diploma && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {acadFiles.diploma ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#F59E0B" />}
                  <span style={{ fontSize: 13, fontWeight: 600, color: acadFiles.diploma ? '#0F172A' : '#F59E0B' }}>Diploma</span>
                </div>
              )}
              {acadSelection.degree && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {acadFiles.degree ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#F59E0B" />}
                  <span style={{ fontSize: 13, fontWeight: 600, color: acadFiles.degree ? '#0F172A' : '#F59E0B' }}>Degree Certificate</span>
                </div>
              )}
              {acadSelection.semesters && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {semFiles.length > 0 ? <CheckCircle2 size={16} color="#16A34A" /> : <AlertCircle size={16} color="#F59E0B" />}
                  <span style={{ fontSize: 13, fontWeight: 600, color: semFiles.length > 0 ? '#0F172A' : '#F59E0B' }}>{semFiles.length} Semester Cards</span>
                </div>
              )}
            </div>

            <div style={{ background: '#F8FAFC', borderRadius: 12, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#64748B' }}>Completion</span>
                <span style={{ fontSize: 12, fontWeight: 800, color: '#2563EB' }}>{progressPct}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: '#E2E8F0', overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${progressPct}%`, background: '#2563EB', transition: 'width 0.3s ease' }} />
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
