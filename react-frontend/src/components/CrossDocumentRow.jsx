import { useState, useEffect } from 'react';
import { GitCompare, CheckCircle2, AlertTriangle, X } from 'lucide-react';

export default function CrossDocumentRow({
  label,
  sources = [], // [{ source: 'AADHAAR', value: 'Aditya' }, ...]
  finalValue,
  onSetFinal,
  mono = false
}) {

  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(finalValue || '');

  useEffect(() => {
    setEditValue(finalValue || '');
  }, [finalValue]);

  const handleSave = () => {
    if (onSetFinal) onSetFinal(editValue);
    setIsEditing(false);
  };

  // Check agreement among sources (ignoring empty)
  const validValues = sources.map(s => s.value).filter(Boolean).map(s => String(s).toLowerCase().trim());
  const allMatch = validValues.length > 1 && validValues.every(v => v === validValues[0]);
  const hasMismatch = validValues.length > 1 && !allMatch;

  return (
    <div style={{
      border: '1px solid #E5E7EB',
      borderRadius: 12,
      overflow: 'hidden',
      background: '#FAFAFA',
      marginBottom: 16
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 16px',
        background: '#FFFFFF',
        borderBottom: '1px solid #E5E7EB',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <span style={{ fontSize: 11.5, fontWeight: 700, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {label}
        </span>
        {hasMismatch ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 20, background: '#FEF2F2', border: '1px solid #FECACA', fontSize: 11, fontWeight: 700, color: '#DC2626' }}>
            <X size={11} /> Mismatch
          </div>
        ) : allMatch ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 20, background: '#F0FDF4', border: '1px solid #BBF7D0', fontSize: 11, fontWeight: 700, color: '#16A34A' }}>
            <CheckCircle2 size={11} /> All Match
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '3px 10px', borderRadius: 20, background: '#F9FAFB', border: '1px solid #E5E7EB', fontSize: 11, fontWeight: 700, color: '#6B7280' }}>
            Not Enough Data
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'row', padding: 0 }}>
        {/* Render each source horizontally */}
        {sources.map((src, idx) => (
          <div key={idx} style={{ flex: 1, padding: '16px', borderRight: '1px solid #E5E7EB', display: 'flex', flexDirection: 'column' }}>
            <div style={{
              fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748B', marginBottom: 6
            }}>
              {src.source}
            </div>
            <div style={{
              fontSize: mono ? 13 : 14, fontWeight: src.value ? 600 : 400, color: src.value ? '#0F172A' : '#94A3B8',
              fontStyle: src.value ? 'normal' : 'italic',
              fontFamily: mono ? "'SF Mono', monospace" : 'inherit', wordBreak: 'break-word', marginBottom: 12
            }}>
              {src.value || (src.source.includes('USER ENTERED') ? 'Not Provided' : 'Not Extracted')}
            </div>
            {src.value && (
              <button 
                onClick={() => onSetFinal && onSetFinal(src.value)}
                style={{ marginTop: 'auto', alignSelf: 'flex-start', fontSize: 10, padding: '4px 10px', background: '#FFFFFF', color: '#374151', borderRadius: 4, border: '1px solid #D1D5DB', cursor: 'pointer', fontWeight: 600 }}
              >
                Use {src.source}
              </button>
            )}
          </div>
        ))}

        {/* FINAL VERIFIED COLUMN */}
        <div style={{ flex: 1.2, minWidth: 200, padding: '16px', display: 'flex', flexDirection: 'column', background: '#FDFCF8' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            fontSize: 10, fontWeight: 700, textTransform: 'uppercase',
            letterSpacing: '0.08em', color: '#16A34A',
            background: '#F0FDF4', padding: '2px 7px', borderRadius: 20, marginBottom: 12, alignSelf: 'flex-start'
          }}>
            FINAL VERIFIED
          </div>
          
          {isEditing ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 'auto' }}>
              <input 
                type="text" 
                value={editValue} 
                onChange={e => setEditValue(e.target.value)}
                style={{ width: '100%', boxSizing: 'border-box', fontSize: 13, padding: '6px 8px', border: '1px solid #D1D5DB', borderRadius: 4, fontFamily: mono ? "'SF Mono', monospace" : 'inherit' }}
                autoFocus
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSave();
                  if (e.key === 'Escape') setIsEditing(false);
                }}
              />
              <div style={{ display: 'flex', gap: 6 }}>
                <button onClick={handleSave} style={{ flex: 1, padding: '6px', background: '#16A34A', color: 'white', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 600 }}>Save</button>
                <button onClick={() => setIsEditing(false)} style={{ flex: 1, padding: '6px', background: '#F1F5F9', color: '#64748B', border: 'none', borderRadius: 4, cursor: 'pointer', fontSize: 11, fontWeight: 600 }}>Cancel</button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 10, marginTop: 'auto' }}>
              <div style={{
                fontSize: mono ? 13 : 15, fontWeight: finalValue ? 700 : 400,
                color: finalValue ? '#0F172A' : '#94A3B8',
                fontStyle: finalValue ? 'normal' : 'italic',
                fontFamily: mono ? "'SF Mono', monospace" : 'inherit',
                wordBreak: 'break-word',
              }}>
                {finalValue || 'No final value'}
              </div>
              <button onClick={() => { setEditValue(finalValue || ''); setIsEditing(true); }} style={{ fontSize: 11, padding: '4px 12px', background: '#FFFFFF', border: '1px solid #CBD5E1', borderRadius: 4, color: '#475569', cursor: 'pointer', fontWeight: 600 }}>
                Edit
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
