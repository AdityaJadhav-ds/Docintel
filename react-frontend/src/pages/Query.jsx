import { useState, useEffect } from 'react';
import Navbar from '../components/Navbar';
import { getApiBase } from '../api/api';
import {
  Search, Sparkles, Filter, ShieldCheck, AlertTriangle,
  FileWarning, Users, CheckCircle2, GraduationCap,
  TrendingUp, TrendingDown, BookOpen, Award, ChevronRight,
  BarChart3, Zap, X
} from 'lucide-react';

const API_BASE = getApiBase();

const DOC_LABELS = { aadhaar:'AD', pan:'PAN', tenth:'10th', twelfth:'12th', degree:'Deg', diploma:'Dip', semester:'Sem' };
const DOC_COLORS = { aadhaar:'#2563EB', pan:'#7C3AED', tenth:'#16A34A', twelfth:'#0891B2', degree:'#9333EA', diploma:'#EA580C', semester:'#0284C7' };
const DOC_BG    = { aadhaar:'#DBEAFE', pan:'#EDE9FE', tenth:'#DCFCE7', twelfth:'#CFFAFE', degree:'#F3E8FF', diploma:'#FFEDD5', semester:'#E0F2FE' };

const KYC_FILTERS = [
  { label:'Missing Aadhaar', q:'missing aadhaar', icon:FileWarning, color:'#D97706' },
  { label:'Missing PAN',     q:'missing pan',     icon:FileWarning, color:'#D97706' },
  { label:'Mismatch',        q:'mismatch',        icon:AlertTriangle, color:'#EF4444' },
  { label:'Age > 18',        q:'age > 18',        icon:Users, color:'#2563EB' },
];

const ACADEMIC_FILTERS = [
  { label:'Above 75%',       q:'above 75',        color:'#16A34A' },
  { label:'Below 60%',       q:'below 60',        color:'#EF4444' },
  { label:'Distinction',     q:'distinction',     color:'#7C3AED' },
  { label:'First Class',     q:'first class',     color:'#0891B2' },
  { label:'Toppers',         q:'toppers',         color:'#F59E0B' },
  { label:'CGPA > 8',        q:'cgpa > 8',        color:'#9333EA' },
  { label:'Low Marks',       q:'low marks',       color:'#DC2626' },
  { label:'Degree',          q:'degree',          color:'#0284C7' },
  { label:'Has 10th',        q:'10th',            color:'#16A34A' },
  { label:'Has 12th',        q:'12th',            color:'#0891B2' },
  { label:'No Academic',     q:'missing academic',color:'#94A3B8' },
  { label:'All Academic',    q:'all academic',    color:'#9333EA' },
];

const s = (style) => style;

function DocBadge({ type }) {
  return (
    <span style={{
      display:'inline-flex', alignItems:'center',
      padding:'2px 8px', borderRadius:20,
      fontSize:10, fontWeight:700,
      color: DOC_COLORS[type] || '#475569',
      background: DOC_BG[type] || '#F1F5F9',
      marginRight:3,
    }}>
      {DOC_LABELS[type] || type}
    </span>
  );
}

function ScorePill({ pct, cgpa }) {
  if (!pct && !cgpa) return <span style={{fontSize:12,color:'#CBD5E1'}}>—</span>;
  if (cgpa) return (
    <span style={{fontSize:13,fontWeight:800,color:'#7C3AED',background:'#F3E8FF',padding:'2px 8px',borderRadius:6}}>
      {cgpa.toFixed(1)} CGPA
    </span>
  );
  const color = pct >= 75 ? '#16A34A' : pct >= 60 ? '#0891B2' : '#EF4444';
  const bg    = pct >= 75 ? '#DCFCE7' : pct >= 60 ? '#CFFAFE' : '#FEE2E2';
  return (
    <span style={{fontSize:13,fontWeight:800,color,background:bg,padding:'2px 8px',borderRadius:6}}>
      {pct.toFixed(1)}%
    </span>
  );
}

function AcademicStatus({ pct, cgpa }) {
  if (!pct && !cgpa) return <span style={{color:'#94A3B8',fontSize:12}}>No data</span>;
  const val = pct || (cgpa ? cgpa * 10 : 0);
  const [label, color] = val >= 75 ? ['Distinction','#16A34A'] : val >= 60 ? ['First Class','#0891B2'] : val >= 40 ? ['Pass','#F59E0B'] : ['At Risk','#EF4444'];
  return <span style={{fontSize:11,fontWeight:700,color,background:`${color}18`,padding:'2px 8px',borderRadius:20}}>{label}</span>;
}

function InsightCard({ icon: Icon, label, value, color, bg }) {
  return (
    <div style={{ padding:'12px 14px', borderRadius:10, background:bg, border:`1px solid ${color}22`, display:'flex', alignItems:'center', gap:10 }}>
      <div style={{ width:32, height:32, borderRadius:8, background:`${color}18`, display:'flex', alignItems:'center', justifyContent:'center', flexShrink:0 }}>
        <Icon size={16} color={color} />
      </div>
      <div>
        <div style={{ fontSize:11, fontWeight:600, color:'#64748B', textTransform:'uppercase', letterSpacing:'0.05em' }}>{label}</div>
        <div style={{ fontSize:17, fontWeight:800, color:'#0F172A', lineHeight:1.2 }}>{value}</div>
      </div>
    </div>
  );
}

export default function DataIntelligenceHub() {
  const [nlq, setNlq]         = useState('');
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);
  const [activeGroup, setActiveGroup] = useState('kyc'); // 'kyc' | 'academic'

  const fetchInsights = async (q = '') => {
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/insights?${new URLSearchParams({ q, search: '' })}`);
      const data = await res.json();
      setRecords(data.results || []);
    } catch { setRecords([]); }
    finally  { setLoading(false); }
  };

  useEffect(() => { fetchInsights(''); }, []);

  const handleRun  = () => fetchInsights(nlq);
  const applyQuick = (q) => { setNlq(q); fetchInsights(q); };
  const clear      = () => { setNlq(''); fetchInsights(''); };

  // ── KPI calculations ─────────────────────────────────────────────────
  const total      = records.length;
  const clean      = records.filter(r => r.aadhaar_available && r.pan_available).length;
  const missingA   = records.filter(r => !r.aadhaar_available).length;
  const missingP   = records.filter(r => !r.pan_available).length;
  const withAcad   = records.filter(r => r.academic_available).length;

  const pcts       = records.map(r => r.academic_percentage).filter(Boolean);
  const cgpas      = records.map(r => r.academic_cgpa).filter(Boolean);
  const avgPct     = pcts.length  ? (pcts.reduce((a,b)=>a+b,0)/pcts.length).toFixed(1) : null;
  const avgCgpa    = cgpas.length ? (cgpas.reduce((a,b)=>a+b,0)/cgpas.length).toFixed(2) : null;
  const above75    = pcts.filter(p => p >= 75).length;
  const below60    = pcts.filter(p => p < 60).length;

  const card = (style) => ({ background:'#FFFFFF', border:'1px solid #E5E7EB', borderRadius:14, padding:16, ...style });

  return (
    <div style={{ flex:1, background:'#F8FAFC' }}>
      <Navbar title="Intelligence Hub" subtitle="Unified Document + Academic AI Analysis Platform" />

      <div style={{ padding:24, maxWidth:1400, margin:'0 auto', display:'flex', flexDirection:'column', gap:20 }}>

        {/* ── QUERY BAR ── */}
        <div style={card({ display:'flex', flexDirection:'column', gap:12 })}>
          <div style={{ display:'flex', alignItems:'center', gap:12 }}>
            <div style={{ position:'relative', flex:1 }}>
              <Search size={19} style={{ position:'absolute', left:14, top:'50%', transform:'translateY(-50%)', color: focused ? '#2563EB' : '#94A3B8', transition:'color 150ms' }} />
              <input
                value={nlq}
                onChange={e => setNlq(e.target.value)}
                onKeyDown={e => e.key==='Enter' && handleRun()}
                onFocus={() => setFocused(true)}
                onBlur={() => setFocused(false)}
                placeholder='Ask anything: "students above 75%", "missing aadhaar", "toppers", "cgpa > 8"…'
                style={{
                  width:'100%', height:50, padding:'0 14px 0 44px',
                  borderRadius:12, border:`1.5px solid ${focused ? '#2563EB' : '#E2E8F0'}`,
                  fontSize:14, color:'#0F172A', outline:'none',
                  boxShadow: focused ? '0 0 0 3px rgba(37,99,235,0.12)' : 'none', transition:'all 150ms',
                }}
              />
              {nlq && (
                <button onClick={clear} style={{ position:'absolute', right:12, top:'50%', transform:'translateY(-50%)', background:'none', border:'none', cursor:'pointer', color:'#94A3B8', display:'flex' }}>
                  <X size={16} />
                </button>
              )}
            </div>
            <button
              onClick={handleRun}
              disabled={loading}
              style={{
                height:50, padding:'0 22px', background:'linear-gradient(135deg,#1D4ED8,#2563EB)',
                color:'#fff', border:'none', borderRadius:12, fontSize:14, fontWeight:700,
                cursor: loading ? 'not-allowed' : 'pointer', display:'flex', alignItems:'center',
                gap:8, flexShrink:0, opacity: loading ? 0.75 : 1, boxShadow:'0 4px 12px rgba(37,99,235,0.3)',
              }}
            >
              {loading
                ? <div style={{ width:16, height:16, borderRadius:'50%', border:'2px solid rgba(255,255,255,0.3)', borderTopColor:'#fff', animation:'spin 0.8s linear infinite' }} />
                : <Sparkles size={17} />}
              Analyze
            </button>
          </div>

          {/* Filter group tabs */}
          <div style={{ display:'flex', alignItems:'center', gap:8, flexWrap:'wrap' }}>
            <div style={{ display:'flex', background:'#F1F5F9', borderRadius:8, padding:3, gap:2, marginRight:8 }}>
              {[['kyc','KYC Filters'],['academic','Academic Filters']].map(([key,label]) => (
                <button key={key} onClick={() => setActiveGroup(key)} style={{
                  padding:'5px 14px', borderRadius:6, border:'none', cursor:'pointer', fontSize:12, fontWeight:700,
                  background: activeGroup===key ? '#FFFFFF' : 'transparent',
                  color: activeGroup===key ? '#0F172A' : '#64748B',
                  boxShadow: activeGroup===key ? '0 1px 3px rgba(0,0,0,0.1)' : 'none',
                  transition:'all 0.12s',
                }}>{label}</button>
              ))}
            </div>

            {activeGroup === 'kyc' && KYC_FILTERS.map(f => {
              const active = nlq === f.q;
              return (
                <button key={f.q} onClick={() => applyQuick(f.q)} style={{
                  height:30, padding:'0 12px', borderRadius:999, fontSize:12, fontWeight:600,
                  border:`1px solid ${active ? f.color+'55' : '#E2E8F0'}`,
                  background: active ? f.color+'15' : '#F8FAFC',
                  color: active ? f.color : '#475569', cursor:'pointer', display:'flex', alignItems:'center', gap:5,
                  transition:'all 0.12s',
                }}>
                  {f.icon && <f.icon size={12} />} {f.label}
                </button>
              );
            })}

            {activeGroup === 'academic' && ACADEMIC_FILTERS.map(f => {
              const active = nlq === f.q;
              return (
                <button key={f.q} onClick={() => applyQuick(f.q)} style={{
                  height:30, padding:'0 12px', borderRadius:999, fontSize:12, fontWeight:600,
                  border:`1px solid ${active ? f.color+'55' : '#E2E8F0'}`,
                  background: active ? f.color+'15' : '#F8FAFC',
                  color: active ? f.color : '#475569', cursor:'pointer',
                  transition:'all 0.12s',
                }}>
                  {f.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* ── KPI ROW ── */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(7,1fr)', gap:12 }}>
          {[
            { label:'Total',        val:total,    icon:Users,        color:'#2563EB', bg:'#EFF6FF' },
            { label:'Clean KYC',    val:clean,    icon:ShieldCheck,  color:'#16A34A', bg:'#F0FDF4' },
            { label:'No Aadhaar',   val:missingA, icon:FileWarning,  color:'#D97706', bg:'#FFFBEB' },
            { label:'No PAN',       val:missingP, icon:FileWarning,  color:'#D97706', bg:'#FFFBEB' },
            { label:'With Academic',val:withAcad, icon:GraduationCap,color:'#7C3AED', bg:'#FAF5FF' },
            { label:'Avg Score',    val: avgPct ? `${avgPct}%` : avgCgpa ? `${avgCgpa} GPA` : '—', icon:BarChart3, color:'#0891B2', bg:'#ECFEFF' },
            { label:'Above 75%',    val:above75,  icon:Award,        color:'#16A34A', bg:'#F0FDF4' },
          ].map(k => (
            <div key={k.label} style={{ background:k.bg, borderRadius:12, padding:'12px 14px', border:`1px solid ${k.color}22` }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:6 }}>
                <span style={{ fontSize:10, fontWeight:700, color:'#64748B', textTransform:'uppercase', letterSpacing:'0.05em' }}>{k.label}</span>
                <k.icon size={14} color={k.color} />
              </div>
              <div style={{ fontSize:22, fontWeight:800, color:k.color, lineHeight:1 }}>{k.val}</div>
            </div>
          ))}
        </div>

        {/* ── MAIN CONTENT ── */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 300px', gap:20, alignItems:'start' }}>

          {/* Results Table */}
          <div style={card({ overflow:'hidden' })}>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:14 }}>
              <div style={{ display:'flex', alignItems:'center', gap:8 }}>
                <Filter size={17} color="#64748B" />
                <span style={{ fontSize:15, fontWeight:700, color:'#0F172A' }}>Query Results</span>
                <span style={{ fontSize:12, fontWeight:600, color:'#64748B', background:'#F1F5F9', padding:'2px 10px', borderRadius:20 }}>{total}</span>
              </div>
              {nlq && (
                <span style={{ fontSize:12, color:'#64748B', background:'#F8FAFC', border:'1px solid #E2E8F0', padding:'3px 10px', borderRadius:20 }}>
                  "{nlq}"
                </span>
              )}
            </div>

            <div style={{ overflowX:'auto' }}>
              <table style={{ width:'100%', borderCollapse:'collapse' }}>
                <thead>
                  <tr style={{ background:'#F8FAFC' }}>
                    {['Name','Documents','Academic Score','Academic Status','Actions'].map(h => (
                      <th key={h} style={{ padding:'10px 14px', fontSize:11, fontWeight:700, color:'#64748B', borderBottom:'1px solid #E5E7EB', textTransform:'uppercase', letterSpacing:'0.05em', textAlign: h==='Actions'?'right':'left' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {records.length === 0 ? (
                    <tr>
                      <td colSpan="5" style={{ padding:'60px 0', textAlign:'center', color:'#94A3B8' }}>
                        <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:10 }}>
                          <Search size={32} color="#CBD5E1" strokeWidth={1.5} />
                          <span style={{ fontSize:14, fontWeight:500 }}>{loading ? 'Searching…' : 'No records match your query'}</span>
                        </div>
                      </td>
                    </tr>
                  ) : records.map((u, i) => {
                    const allDocs = [
                      ...(u.aadhaar_available ? ['aadhaar'] : []),
                      ...(u.pan_available     ? ['pan']     : []),
                      ...(u.academic_doc_types || []),
                    ];
                    return (
                      <tr key={u.user_id || i}
                        style={{ borderBottom:'1px solid #F1F5F9', transition:'background 120ms' }}
                        onMouseEnter={e => e.currentTarget.style.background='#F8FAFC'}
                        onMouseLeave={e => e.currentTarget.style.background='transparent'}
                      >
                        <td style={{ padding:'12px 14px' }}>
                          <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                            <div style={{ width:32, height:32, borderRadius:'50%', background:'linear-gradient(135deg,#EFF6FF,#DBEAFE)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:13, fontWeight:800, color:'#2563EB', flexShrink:0 }}>
                              {(u.name || '?')[0].toUpperCase()}
                            </div>
                            <div>
                              <div style={{ fontSize:13, fontWeight:700, color:'#0F172A' }}>{u.name || '—'}</div>
                              <div style={{ fontSize:11, color:'#94A3B8' }}>ID #{u.user_id} {u.age ? `· ${u.age}y` : ''}</div>
                            </div>
                          </div>
                        </td>
                        <td style={{ padding:'12px 14px' }}>
                          <div style={{ display:'flex', flexWrap:'wrap', gap:2 }}>
                            {allDocs.length === 0
                              ? <span style={{ fontSize:11, color:'#D97706', fontWeight:600 }}>No docs</span>
                              : allDocs.map(d => <DocBadge key={d} type={d} />)
                            }
                          </div>
                        </td>
                        <td style={{ padding:'12px 14px' }}>
                          <ScorePill pct={u.academic_percentage} cgpa={u.academic_cgpa} />
                        </td>
                        <td style={{ padding:'12px 14px' }}>
                          <AcademicStatus pct={u.academic_percentage} cgpa={u.academic_cgpa} />
                        </td>
                        <td style={{ padding:'12px 14px', textAlign:'right' }}>
                          <div style={{ display:'flex', gap:5, justifyContent:'flex-end' }}>
                            {!u.aadhaar_available && <span style={{ padding:'3px 7px', borderRadius:6, background:'#FEF3C7', color:'#D97706', fontSize:10, fontWeight:700 }}>No AD</span>}
                            {!u.pan_available     && <span style={{ padding:'3px 7px', borderRadius:6, background:'#FEF3C7', color:'#D97706', fontSize:10, fontWeight:700 }}>No PAN</span>}
                            {u.aadhaar_available && u.pan_available && !u.academic_available && (
                              <span style={{ padding:'3px 7px', borderRadius:6, background:'#DCFCE7', color:'#16A34A', fontSize:10, fontWeight:700, display:'flex', alignItems:'center', gap:3 }}>
                                <CheckCircle2 size={10} /> KYC ✓
                              </span>
                            )}
                            {u.academic_available && (
                              <span style={{ padding:'3px 7px', borderRadius:6, background:'#F3E8FF', color:'#7C3AED', fontSize:10, fontWeight:700, display:'flex', alignItems:'center', gap:3 }}>
                                <GraduationCap size={10} /> Academic
                              </span>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Smart Insights Panel */}
          <div style={{ display:'flex', flexDirection:'column', gap:14 }}>

            {/* KYC Insights */}
            <div style={card({ display:'flex', flexDirection:'column', gap:12 })}>
              <div style={{ fontSize:13, fontWeight:700, color:'#0F172A', display:'flex', alignItems:'center', gap:7, marginBottom:2 }}>
                <Zap size={15} color="#D97706" /> KYC Intelligence
              </div>
              {total === 0 ? (
                <div style={{ color:'#94A3B8', fontSize:13, textAlign:'center', padding:'12px 0' }}>No data</div>
              ) : (
                <>
                  <InsightCard icon={ShieldCheck} label="Complete Profiles" value={`${((clean/total)*100).toFixed(0)}%`} color="#16A34A" bg="#F0FDF4" />
                  {missingA > 0 && <InsightCard icon={FileWarning} label="Missing Aadhaar" value={missingA} color="#D97706" bg="#FFFBEB" />}
                  {missingP > 0 && <InsightCard icon={FileWarning} label="Missing PAN"     value={missingP} color="#D97706" bg="#FFFBEB" />}
                  {missingA === 0 && missingP === 0 && (
                    <div style={{ fontSize:12, color:'#16A34A', textAlign:'center', fontWeight:600 }}>✓ All KYC complete</div>
                  )}
                </>
              )}
            </div>

            {/* Academic Insights */}
            <div style={card({ display:'flex', flexDirection:'column', gap:12 })}>
              <div style={{ fontSize:13, fontWeight:700, color:'#0F172A', display:'flex', alignItems:'center', gap:7, marginBottom:2 }}>
                <GraduationCap size={15} color="#7C3AED" /> Academic Intelligence
              </div>
              {withAcad === 0 ? (
                <div style={{ color:'#94A3B8', fontSize:12, textAlign:'center', padding:'8px 0' }}>No academic data in current results</div>
              ) : (
                <>
                  <InsightCard icon={BarChart3}      label="Avg Performance" value={avgPct ? `${avgPct}%` : avgCgpa ? `${avgCgpa} GPA` : '—'} color="#0891B2" bg="#ECFEFF" />
                  <InsightCard icon={TrendingUp}     label="Above 75%"       value={above75}  color="#16A34A" bg="#F0FDF4" />
                  {below60 > 0 && <InsightCard icon={TrendingDown} label="Below 60% (Risk)" value={below60} color="#EF4444" bg="#FEF2F2" />}
                  <InsightCard icon={BookOpen}       label="With Academics"  value={withAcad} color="#7C3AED" bg="#FAF5FF" />
                  <InsightCard icon={Award}          label="Academic Coverage" value={`${((withAcad/total)*100).toFixed(0)}%`} color="#F59E0B" bg="#FFFBEB" />
                </>
              )}
            </div>

            {/* Quick Queries */}
            <div style={card({ display:'flex', flexDirection:'column', gap:8 })}>
              <div style={{ fontSize:12, fontWeight:700, color:'#64748B', textTransform:'uppercase', letterSpacing:'0.05em', marginBottom:2 }}>
                Try These Queries
              </div>
              {[
                'show toppers','students above 75%','low marks','cgpa > 8',
                'missing academic','degree students','all academic docs',
              ].map(q => (
                <button key={q} onClick={() => applyQuick(q)} style={{
                  width:'100%', padding:'7px 10px', borderRadius:8, border:'1px solid #E2E8F0',
                  background:'#F8FAFC', fontSize:12, fontWeight:500, color:'#475569',
                  cursor:'pointer', textAlign:'left', display:'flex', justifyContent:'space-between',
                  alignItems:'center', transition:'all 0.12s',
                }}
                  onMouseEnter={e => { e.currentTarget.style.background='#EFF6FF'; e.currentTarget.style.borderColor='#BFDBFE'; e.currentTarget.style.color='#1D4ED8'; }}
                  onMouseLeave={e => { e.currentTarget.style.background='#F8FAFC'; e.currentTarget.style.borderColor='#E2E8F0'; e.currentTarget.style.color='#475569'; }}
                >
                  {q} <ChevronRight size={12} />
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
