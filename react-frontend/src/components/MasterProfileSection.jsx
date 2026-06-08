import { useState, useEffect } from 'react';
import { CheckCircle2, ShieldCheck } from 'lucide-react';

function MasterFieldRow({ label, sources = [], finalValue, onSetFinal, mono = false }) {
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(finalValue || '');

  useEffect(() => {
    setEditValue(finalValue || '');
  }, [finalValue]);

  const handleSave = () => {
    if (onSetFinal) onSetFinal(editValue);
    setIsEditing(false);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '16px', borderBottom: '1px solid #F3F4F6' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {label}
      </div>
      <div style={{ display: 'flex', gap: 20 }}>
        {/* LEFT: Sources list */}
        <div style={{ flex: 1.5, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {sources.map((src, idx) => (
            <button
              key={idx}
              onClick={() => onSetFinal && onSetFinal(src.value)}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                padding: '6px 12px', background: finalValue === src.value ? '#EFF6FF' : '#F8FAFC',
                border: `1px solid ${finalValue === src.value ? '#BFDBFE' : '#E2E8F0'}`,
                borderRadius: 8, cursor: 'pointer', minWidth: 140, textAlign: 'left'
              }}
            >
              <span style={{ fontSize: 9, fontWeight: 700, color: finalValue === src.value ? '#2563EB' : '#64748B', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>
                {src.source}
              </span>
              <span style={{
                fontSize: mono ? 12 : 13, fontWeight: 600, color: finalValue === src.value ? '#1D4ED8' : '#0F172A',
                fontFamily: mono ? "'SF Mono', monospace" : 'inherit', wordBreak: 'break-word'
              }}>
                {src.value}
              </span>
            </button>
          ))}
        </div>

        {/* RIGHT: Final Value */}
        <div style={{ flex: 1, padding: '12px 16px', background: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: 10, display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 8 }}>
            <CheckCircle2 size={12} color="#16A34A" />
            <span style={{ fontSize: 10, fontWeight: 700, color: '#16A34A', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Final Verified
            </span>
          </div>
          
          {isEditing ? (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 'auto' }}>
              <input 
                type="text" 
                value={editValue} 
                onChange={e => setEditValue(e.target.value)}
                style={{ flex: 1, fontSize: 13, padding: '6px 8px', border: '1px solid #16A34A', borderRadius: 4, fontFamily: mono ? "'SF Mono', monospace" : 'inherit', outline: 'none' }}
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSave();
                  if (e.key === 'Escape') setIsEditing(false);
                }}
              />
              <button onClick={handleSave} style={{ padding: '6px 12px', background: '#16A34A', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 600 }}>Save</button>
            </div>
          ) : (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'auto', gap: 10 }}>
              <div style={{
                fontSize: mono ? 14 : 16, fontWeight: 700, color: '#065F46',
                fontFamily: mono ? "'SF Mono', monospace" : 'inherit', wordBreak: 'break-word'
              }}>
                {finalValue || 'Pending Selection'}
              </div>
              <button onClick={() => { setEditValue(finalValue || ''); setIsEditing(true); }} style={{ fontSize: 11, padding: '4px 10px', background: '#FFFFFF', border: '1px solid #86EFAC', borderRadius: 4, color: '#15803D', cursor: 'pointer', fontWeight: 600 }}>
                Edit
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MasterProfileSection({ user }) {
  if (!user) return null;

  const overrides = user.final_overrides || {};
  const setFinal = user.set_final_override || (() => {});

  const getSources = (field) => {
    const s = [];
    
    // KYC
    const e = user.original_name || user.name || user.full_name;
    const aNum = user.entered_aadhaar_number;
    const pNum = user.entered_pan_number;
    const eDob = user.dob;
    
    const xA_name = user.aadhaar?.name;
    const xA_num  = user.aadhaar?.aadhaar_number;
    const xA_dob  = user.aadhaar?.dob;
    
    const xP_name = user.pan?.name;
    const xP_num  = user.pan?.pan_number;
    const xP_dob  = user.pan?.dob;

    if (field === 'name') {
      if (xA_name) s.push({ source: 'Aadhaar OCR', value: xA_name });
      if (xP_name) s.push({ source: 'PAN OCR', value: xP_name });
      ['tenth', 'twelfth', 'degree', 'diploma'].forEach(t => {
        const r = user.academic_results?.[t]?.candidate_name;
        if (r) s.push({ source: `${t} OCR`, value: r });
      });
      if (e) s.push({ source: 'User Entered', value: e });
    }

    if (field === 'aadhaar') {
      if (xA_num) s.push({ source: 'Aadhaar OCR', value: xA_num });
      if (aNum) s.push({ source: 'User Entered', value: aNum });
    }

    if (field === 'pan') {
      if (xP_num) s.push({ source: 'PAN OCR', value: xP_num });
      if (pNum) s.push({ source: 'User Entered', value: pNum });
    }

    if (field === 'dob') {
      if (xA_dob) s.push({ source: 'Aadhaar OCR', value: xA_dob });
      if (xP_dob) s.push({ source: 'PAN OCR', value: xP_dob });
      ['tenth', 'twelfth', 'degree', 'diploma'].forEach(t => {
        const r = user.academic_results?.[t]?.dob;
        if (r) s.push({ source: `${t} OCR`, value: r });
      });
      if (eDob) s.push({ source: 'User Entered', value: eDob });
    }

    if (field === 'percentage') {
      ['tenth', 'twelfth'].forEach(t => {
        const r = user.academic_results?.[t]?.academic_score;
        if (r) s.push({ source: `${t} OCR`, value: String(r) });
        const en = user.academic_inputs?.[t]?.percentage;
        if (en) s.push({ source: `${t} Entered`, value: String(en) });
      });
    }

    if (field === 'cgpa') {
      ['degree', 'diploma', 'semesters'].forEach(t => {
        const r = user.academic_results?.[t]?.academic_score;
        if (r) s.push({ source: `${t} OCR`, value: String(r) });
        const en = user.academic_inputs?.[t]?.cgpa || user.academic_inputs?.[t]?.percentage;
        if (en) s.push({ source: `${t} Entered`, value: String(en) });
      });
    }

    // deduplicate sources array by value (case-insensitive)
    const unique = [];
    const seen = new Set();
    for (const src of s) {
      if (!src.value) continue;
      const key = String(src.value).trim().toLowerCase();
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(src);
      }
    }
    return unique;
  };

  const nameSources = getSources('name');
  const aadhaarSources = getSources('aadhaar');
  const panSources = getSources('pan');
  const dobSources = getSources('dob');
  const pctSources = getSources('percentage');
  const cgpaSources = getSources('cgpa');

  // Auto-selection default (priority is first item in deduplicated array, because we pushed Aadhaar > PAN > Academics > Entered)
  const getFinal = (key, sources) => {
    if (overrides[key] !== undefined) return overrides[key];
    if (user[`final_${key}`]) return user[`final_${key}`]; // From DB
    return sources.length > 0 ? sources[0].value : '';
  };

  return (
    <div style={{ background: '#FFFFFF', border: '2px solid #22C55E', borderRadius: 16, overflow: 'hidden', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)', marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '16px 20px', background: '#F0FDF4', borderBottom: '1px solid #BBF7D0' }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, background: '#DCFCE7', border: '1px solid #86EFAC', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <ShieldCheck size={18} color="#15803D" />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: '#064E3B', letterSpacing: '0.05em' }}>FINAL VERIFIED IDENTITY</h2>
          <p style={{ margin: 0, fontSize: 12, color: '#16A34A', fontWeight: 600 }}>Single Source of Truth for Database Save</p>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <MasterFieldRow label="Full Name" sources={nameSources} finalValue={getFinal('name', nameSources)} onSetFinal={v => setFinal('name', v)} />
        <MasterFieldRow label="Aadhaar Number" sources={aadhaarSources} finalValue={getFinal('aadhaar', aadhaarSources)} onSetFinal={v => setFinal('aadhaar', v)} mono />
        <MasterFieldRow label="PAN Number" sources={panSources} finalValue={getFinal('pan', panSources)} onSetFinal={v => setFinal('pan', v)} mono />
        <MasterFieldRow label="Date of Birth" sources={dobSources} finalValue={getFinal('dob', dobSources)} onSetFinal={v => setFinal('dob', v)} />
        
        {pctSources.length > 0 && (
          <MasterFieldRow label="Percentage (10th/12th)" sources={pctSources} finalValue={getFinal('percentage', pctSources)} onSetFinal={v => setFinal('percentage', v)} />
        )}
        {cgpaSources.length > 0 && (
          <MasterFieldRow label="CGPA (Degree/Diploma)" sources={cgpaSources} finalValue={getFinal('cgpa', cgpaSources)} onSetFinal={v => setFinal('cgpa', v)} />
        )}
      </div>
    </div>
  );
}
