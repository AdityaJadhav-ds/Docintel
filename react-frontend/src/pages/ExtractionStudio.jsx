/**
 * ExtractionStudio.jsx — Stage 2: Positional Visual Text Reconstruction
 *
 * Three render modes (toggle on topbar):
 *  1. FLOW      — plain lines in reading order (Stage 1)
 *  2. POSITIONAL — X-space-padded monospace, columns emerge naturally (Stage 2)
 *  3. EXACT     — every word absolutely positioned at real pixel coords (Stage 3 preview)
 */
import React, { useState, useRef, useCallback, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Download, Copy, FileText, Layout,
  Image as ImageIcon, ZoomIn, ZoomOut, Maximize, X,
  AlignLeft, AlignJustify, Grid,
} from 'lucide-react';

const API = 'http://127.0.0.1:8001';  // backend_v2 OCR engine runs on 8001

// ─────────────────────────────────────────────────────────────────────────────
// CSS
// ─────────────────────────────────────────────────────────────────────────────
function injectFont() {
  if (document.getElementById('es-font-v10')) return;
  const l = document.createElement('link');
  l.id = 'es-font-v10'; l.rel = 'stylesheet';
  l.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap';
  document.head.appendChild(l);
}

function injectCSS() {
  if (document.getElementById('es10-css')) return;
  const s = document.createElement('style');
  s.id = 'es10-css';
  s.textContent = `
    *, *::before, *::after { box-sizing: border-box; margin:0; padding:0; }
    body { font-family:'Inter','Segoe UI',sans-serif; background:#f1f5f9; color:#0f172a; overflow:hidden; }

    ::-webkit-scrollbar { width:6px; height:6px; }
    ::-webkit-scrollbar-track { background:transparent; }
    ::-webkit-scrollbar-thumb { background:#cbd5e1; border-radius:4px; }
    ::-webkit-scrollbar-thumb:hover { background:#94a3b8; }

    /* ── Topbar ─────────────────────────────────────────────────── */
    .topbar {
      height:54px; padding:0 20px; flex-shrink:0;
      display:flex; align-items:center; justify-content:space-between;
      background:white; border-bottom:1px solid #e2e8f0; z-index:50;
    }
    .logo-area { display:flex; align-items:center; gap:8px; font-weight:700; font-size:15px; letter-spacing:-0.3px; }
    .logo-icon { width:26px; height:26px; background:#6366f1; color:white; border-radius:7px; display:flex; align-items:center; justify-content:center; }

    .btn-primary {
      background:#0f172a; color:white; border:none; padding:0 18px; height:36px;
      border-radius:8px; font-weight:600; font-size:13px; font-family:inherit;
      display:flex; align-items:center; gap:7px; cursor:pointer; transition:all .18s;
    }
    .btn-primary:hover:not(:disabled) { background:#1e293b; }
    .btn-primary:disabled { background:#94a3b8; cursor:not-allowed; }

    .btn-outline {
      background:white; border:1px solid #e2e8f0; color:#475569; height:34px; padding:0 13px;
      border-radius:8px; font-weight:500; font-size:12px; font-family:inherit;
      display:flex; align-items:center; gap:6px; cursor:pointer; transition:all .15s;
    }
    .btn-outline:hover  { background:#f8fafc; border-color:#cbd5e1; color:#0f172a; }
    .btn-outline.active { background:#eff0fe; border-color:#6366f1; color:#4338ca; font-weight:600; }

    /* ── Mode switcher pill ─────────────────────────────────────── */
    .mode-pill { display:flex; background:#f1f5f9; border-radius:8px; padding:3px; gap:2px; }
    .mode-btn {
      height:28px; padding:0 12px; border:none; border-radius:6px; font-size:12px;
      font-weight:600; font-family:inherit; cursor:pointer; display:flex; align-items:center; gap:5px;
      background:transparent; color:#64748b; transition:all .15s;
    }
    .mode-btn.active { background:white; color:#0f172a; box-shadow:0 1px 4px rgba(0,0,0,0.08); }

    .file-chip {
      background:#f1f5f9; border:1px solid #e2e8f0; border-radius:8px; padding:5px 10px 5px 8px;
      display:flex; align-items:center; gap:7px; font-size:13px; font-weight:500; color:#334155;
      max-width:300px;
    }
    .file-chip span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }

    /* ── Layout ─────────────────────────────────────────────────── */
    .app-root  { display:flex; flex-direction:column; height:100vh; overflow:hidden; }
    .main-wrap { display:flex; flex:1; overflow:hidden; }
    .left-panel { width:260px; flex-shrink:0; border-right:1px solid #e2e8f0; background:white; display:flex; flex-direction:column; }
    .panel-body { flex:1; overflow-y:auto; padding:14px; display:flex; flex-direction:column; gap:14px; }

    /* ── Thumbnail ──────────────────────────────────────────────── */
    .thumb-wrap { border-radius:10px; overflow:hidden; border:1px solid #e2e8f0; background:#f8fafc; position:relative; }
    .thumb-wrap img { width:100%; display:block; max-height:420px; object-fit:contain; }
    .page-badge { position:absolute; bottom:7px; right:7px; background:rgba(15,23,42,.75); color:white; font-size:10px; font-weight:600; padding:2px 8px; border-radius:20px; }

    /* ── Stats ──────────────────────────────────────────────────── */
    .stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    .stat-card { background:#f8fafc; border:1px solid #e2e8f0; border-radius:9px; padding:10px 12px; }
    .stat-lbl  { font-size:10px; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:.5px; }
    .stat-val  { font-size:20px; font-weight:700; color:#0f172a; margin-top:2px; }
    .stat-sub  { font-size:10px; color:#94a3b8; margin-top:1px; }

    /* ── Workspace ──────────────────────────────────────────────── */
    .workspace {
      flex:1; overflow-y:auto; overflow-x:hidden;
      background:#e8edf4;
      padding:28px 32px; display:flex; flex-direction:column; align-items:center;
      position:relative;
    }

    /* ── Paper ──────────────────────────────────────────────────── */
    .paper-wrap { transform-origin:top center; transition:transform .2s cubic-bezier(.16,1,.3,1); width:100%; display:flex; justify-content:center; }
    .paper {
      width:900px; min-height:1060px; background:white; border-radius:14px;
      padding:48px 52px;
      box-shadow:0 6px 32px rgba(15,23,42,.07), 0 1px 4px rgba(15,23,42,.04);
      position:relative; color:#111827; overflow:hidden;
    }

    /* ── Paper header ────────────────────────────────────────────── */
    .paper-hdr { display:flex; justify-content:space-between; align-items:center; margin-bottom:22px; padding-bottom:16px; border-bottom:1px solid #e2e8f0; }
    .paper-title { font-size:14px; font-weight:700; color:#0f172a; }
    .paper-sub   { font-size:11px; color:#94a3b8; margin-top:1px; }
    .badge { display:inline-flex; align-items:center; gap:5px; padding:3px 9px; border-radius:20px; font-size:10px; font-weight:700; }
    .badge.ocr  { background:#f0fdf4; color:#16a34a; border:1px solid #bbf7d0; }
    .badge.pos  { background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe; }
    .badge.exact{ background:#faf5ff; color:#7c3aed; border:1px solid #ddd6fe; }

    /* ── MODE 1: FLOW — plain lines ─────────────────────────────── */
    .flow-lines { font-family:'Inter',sans-serif; font-size:14px; line-height:1.7; color:#1e293b; }
    .flow-line  { display:block; }
    .flow-line:hover { background:#f0f9ff; border-radius:3px; }

    /* ── MODE 2: POSITIONAL — monospace space-padded ─────────────── */
    .pos-doc {
      font-family:'JetBrains Mono','Fira Code','Courier New',monospace;
      font-size:12.5px; line-height:1.55; color:#0f172a; letter-spacing:0.2px;
      overflow-x:auto; white-space:pre;
      /* subtle rule lines evoke ledger paper */
      background-image: repeating-linear-gradient(
        transparent, transparent 18px,
        rgba(226,232,240,0.4) 18px, rgba(226,232,240,0.4) 19px
      );
      background-attachment: local;
      padding:4px 0;
    }
    .pos-line {
      display:block; white-space:pre;
      border-radius:2px; transition:background .12s;
    }
    .pos-line:hover { background:rgba(99,102,241,.06); }
    .pos-doc .flow-line {
      font-family:'Inter',sans-serif;
      font-size:14px;
      white-space:pre-wrap;
      padding:2px 0;
    }

    /* ── MODE 3: EXACT — absolutely positioned word spans ────────── */
    .exact-canvas {
      position:relative; width:calc(100% - 80px);
      background:#fafafa; border:1px solid #e2e8f0; border-radius:8px;
      overflow-x:auto; white-space:pre;
      padding-right:80px; padding-left:40px;
    }
    .exact-bg { width:100%; display:block; opacity:.1; }
    .exact-word {
      position:absolute;
      font-family:'JetBrains Mono','Fira Code',monospace;
      color:#1e293b; white-space:nowrap;
      background:rgba(255,255,255,.82);
      padding:0 1px; border-radius:1px;
      line-height:1.45;
      letter-spacing:0.3px;
      font-size:12px;
      transition:background .12s;
    }
    .exact-word:hover { background:rgba(99,102,241,.15); z-index:5; }

    /* ── Zoom toolbar ─────────────────────────────────────────────── */
    .zoom-bar {
      position:fixed; bottom:22px; right:22px; background:white; border-radius:9px;
      box-shadow:0 4px 16px rgba(15,23,42,.09); border:1px solid #e2e8f0;
      display:flex; align-items:center; padding:3px; gap:2px; z-index:40;
    }
    .z-btn { width:28px; height:28px; display:flex; align-items:center; justify-content:center; border-radius:5px; border:none; background:transparent; color:#475569; cursor:pointer; transition:.15s; }
    .z-btn:hover { background:#f1f5f9; }
    .z-val { font-size:11px; font-weight:700; padding:0 6px; width:42px; text-align:center; color:#0f172a; }

    /* ── Floating actions ─────────────────────────────────────────── */
    .fabs { position:fixed; top:64px; right:14px; display:flex; flex-direction:column; gap:5px; z-index:40; }
    .fab  {
      width:36px; height:36px; border-radius:9px; background:white; border:1px solid #e2e8f0;
      display:flex; align-items:center; justify-content:center; color:#475569; cursor:pointer;
      box-shadow:0 2px 8px rgba(15,23,42,.06); transition:all .15s; position:relative;
    }
    .fab:hover { background:#f8fafc; color:#6366f1; }
    .fab .tip { position:absolute; right:44px; background:#0f172a; color:white; padding:3px 8px; border-radius:5px; font-size:11px; font-weight:500; white-space:nowrap; opacity:0; pointer-events:none; transition:.12s; }
    .fab:hover .tip { opacity:1; }

    /* ── Loading ─────────────────────────────────────────────────── */
    .scan-line { position:absolute; top:0; left:0; right:0; height:2px; background:linear-gradient(90deg,transparent,#6366f1,transparent); animation:scan 1.8s ease-in-out infinite; z-index:100; }
    @keyframes scan { 0%{top:0;opacity:0} 10%{opacity:1} 90%{opacity:1} 100%{top:100%;opacity:0} }
    .skel { height:13px; background:#f1f5f9; border-radius:3px; margin-bottom:9px; position:relative; overflow:hidden; }
    .skel::after { content:''; position:absolute; inset:0; background:linear-gradient(90deg,transparent,rgba(255,255,255,.6),transparent); animation:shim 1.3s infinite; }
    @keyframes shim { 0%{transform:translateX(-100%)} 100%{transform:translateX(100%)} }
    .spin { animation:spin .8s linear infinite; display:inline-block; }
    @keyframes spin { to{transform:rotate(360deg)} }

    /* ── Empty state ─────────────────────────────────────────────── */
    .empty { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:560px; color:#94a3b8; gap:14px; }
    .empty-title { font-size:17px; font-weight:600; color:#475569; }
    .empty-sub { font-size:13px; }
  `;
  document.head.appendChild(s);
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─────────────────────────────────────────────────────────────────────────────
// MODE 1 — FLOW: plain lines in reading order
// ─────────────────────────────────────────────────────────────────────────────
function FlowRenderer({ lines }) {
  const sorted = [...lines].sort((a, b) => a.y - b.y);
  return (
    <div className="flow-lines">
      {sorted.map((l, i) => (
        <span key={`${l.line_id}-${i}`} className="flow-line"
          title={`y=${l.y}`}>
          {l.text}{'\n'}
        </span>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MODE 2 — POSITIONAL: space-padded monospace  ← THE STAGE 2 BREAKTHROUGH
// Columns emerge naturally from x-coordinate spacing.
// No table engine. No column detection. Pure geometry.
// ─────────────────────────────────────────────────────────────────────────────
function PositionalRenderer({ lines }) {
  const sorted = [...lines].sort((a, b) => a.y - b.y);
  return (
    <div className="pos-doc">
      {sorted.map((l, i) => {
        // Smart Hybrid Mode: Only use positional rendering for dense regions.
        // Headers and paragraphs get flow rendering (plain text).
        const isTable = l.region_type === 'table' || l.region_type === 'kv_block';
        
        if (!isTable) {
          return (
            <span key={`${l.line_id}-${i}`} className="flow-line" title={`y=${l.y} | ${l.region_type}`}>
              {l.text}{'\n'}
            </span>
          );
        }

        // It's a table/kv_block. Render positional logical row.
        const rows = l.logical_row || [{ positioned_text: l.positioned_text, text: l.text, y: l.y }];
        
        return (
          <div key={`${l.line_id}-${i}`} style={{ marginBottom: rows.length > 1 ? 4 : 0 }}>
            {rows.map((row, ri) => (
              <span key={ri} className="pos-line" title={`y=${row.y} | ${l.region_type}`}>
                {row.positioned_text || row.text}{'\n'}
              </span>
            ))}
          </div>
        );
      })}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MODE 3 — EXACT: every word as an absolutely positioned span
// Uses real pixel coordinates scaled to the paper width.
// ─────────────────────────────────────────────────────────────────────────────
function ExactRenderer({ lines, pageImg, pageDims }) {
  const sorted = [...lines].sort((a, b) => a.y - b.y);

  const pageW  = pageDims?.width  || 1200;
  const pageH  = pageDims?.height || 1600;
  const paperW = 796;  // inner paper content width in px
  const paddingRight = 80;
  const paddingLeft = 40;
  const containerWidth = paperW - paddingRight;
  const paperH = Math.round((pageH / pageW) * paperW);
  const scaleX = containerWidth / pageW;
  const scaleY = paperH / pageH;

  return (
    <div className="exact-canvas" style={{ height: paperH }}>
      {pageImg && (
        <img src={pageImg} alt="" className="exact-bg"
          style={{ position: 'absolute', left: paddingLeft, width: containerWidth, height: '100%', objectFit: 'fill' }} />
      )}
      {sorted.map((line, li) =>
        (line.words || []).map((w, wi) => {
          const left   = Math.round(w.x1 * scaleX) + paddingLeft;
          const top    = Math.round(w.y1 * scaleY);
          const height = Math.max(10, Math.round((w.y2 - w.y1) * scaleY));
          return (
            <span
              key={`${li}-${wi}`}
              className="exact-word"
              style={{ left, top, height }}
              title={w.text}
            >
              {w.text}
            </span>
          );
        })
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub }) {
  return (
    <div className="stat-card">
      <div className="stat-lbl">{label}</div>
      <div className="stat-val">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN COMPONENT
// ─────────────────────────────────────────────────────────────────────────────
const MODES = [
  { id: 'flow',       label: 'Flow',       icon: AlignLeft,    badge: 'ocr' },
  { id: 'positional', label: 'Positional', icon: AlignJustify, badge: 'pos' },
  { id: 'exact',      label: 'Exact',      icon: Grid,         badge: 'exact' },
];

export default function ExtractionStudio() {
  const [file,       setFile]       = useState(null);
  const [marathi,    setMarathi]    = useState(false);
  const [mode,       setMode]       = useState('positional');  // default to Stage 2
  const [processing, setProcessing] = useState(false);
  const [result,     setResult]     = useState(null);
  const [statusMsg,  setStatusMsg]  = useState('');
  const [elapsed,    setElapsed]    = useState(0);
  const [processingTime, setProcessingTime] = useState(0);
  const [zoom,       setZoom]       = useState(100);
  const [pageIndex,  setPageIndex]  = useState(0);
  const fileInputRef = useRef(null);
  const containerRef = useRef(null);

  const changePage = (idx) => {
    setPageIndex(idx);
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
    }
  };

  useEffect(() => { injectFont(); injectCSS(); }, []);

  const handleFile = e => {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f); setResult(null); setElapsed(0); setStatusMsg(''); setPageIndex(0);
  };

  const pollStatus = useCallback(async (runId, t0) => {
    for (let i = 0; i < 300; i++) {
      await sleep(2000);  // 2s interval — reduces backend contention
      try {
        const sr = await fetch(`${API}/api/ocr/pipeline/status/${runId}`);
        if (!sr.ok) { console.warn('[DIAG] status non-ok', sr.status, runId); break; }
        const st = await sr.json();
        console.log('[DIAG] Polling:', runId, st);

        // Show real per-stage progress message from backend
        if (st.progress) setStatusMsg(st.progress);

        if (st.overall_status === 'done' || st.overall_status === 'failed' || st.ready) {
          setStatusMsg('');
          const rr = await fetch(`${API}/api/ocr/pipeline/result/${runId}`);
          if (rr.ok) {
            const d = await rr.json();
            console.log('[DIAG] Final result raw:', JSON.stringify(d).slice(0, 500));
            console.log('[DIAG] d.result exists?', !!d.result, '  lines:', d.result?.lines?.length ?? d.lines?.length ?? 'NONE');
            console.log('[DIAG] from_cache:', d.result?.from_cache);
            setResult(d.result || d);
          } else {
            console.error('[DIAG] result fetch failed', rr.status);
          }

          const end = performance.now();
          setProcessingTime(Math.round(end - t0));
          setProcessing(false);
          return;
        }
      } catch (err) { console.error('[DIAG] poll error', err); }
    }
    setProcessing(false); setStatusMsg('Timeout — please retry');
  }, []);

  const handleExtract = async () => {
    if (!file || processing) return;
    setProcessing(true); setResult(null); setElapsed(0); setProcessingTime(0); setStatusMsg('Running OCR…');
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('lang_lock', marathi ? 'mar' : 'eng');
      const start = performance.now();
      const r = await fetch(`${API}/api/ocr/pipeline/start`, { method: 'POST', body: fd });
      if (!r.ok) throw new Error('Start failed');
      const { run_id } = await r.json();
      pollStatus(run_id, start);
    } catch {
      setProcessing(false); setStatusMsg('Error starting extraction');
    }
  };

  // Resolve
  const allLines   = result?.lines || [];
  const cleanText  = result?.clean_text || '';
  const pageImages = result?.images?.pages || [];
  const pageDims   = result?.page_dims || {};
  const wordCount  = result?.word_count || 0;
  const lineCount  = result?.metadata?.line_count || allLines.length;
  const pageCount  = result?.metadata?.page_count || Math.max(1, ...allLines.map(l => (l.page || 0) + 1), 1);
  const currentImg = pageImages[pageIndex] || null;
  const fromCache  = result?.from_cache === true;
  const ocrMs = result ? (result.processing_time_ms || result.elapsed_ms || 0) : 0;
  const ocrTimeStr = fromCache ? '< 1s ⚡' : result ? (ocrMs < 1000 ? `${ocrMs}ms` : `${(ocrMs / 1000).toFixed(1)}s`) : '';
  const totalTimeStr = fromCache ? 'Served from cache' : processingTime < 1000 ? `Total: ${processingTime}ms` : `Total: ${(processingTime / 1000).toFixed(1)}s`;

  // Filter lines to current page
  const pageLines = allLines.filter(l => (l.page ?? 0) === pageIndex);
  const currentMode = MODES.find(m => m.id === mode) || MODES[1];

  return (
    <div className="app-root">

      {/* ── Topbar ── */}
      <div className="topbar">
        <div className="logo-area">
          <div className="logo-icon"><Layout size={13} /></div>
          Extraction Studio
        </div>

        {/* Centre: file chip + mode switcher */}
        <div style={{ flex:1, display:'flex', justifyContent:'center', alignItems:'center', gap:14 }}>
          {file ? (
            <div className="file-chip">
              <FileText size={13} style={{ color:'#6366f1', flexShrink:0 }} />
              <span>{file.name}</span>
              <button onClick={() => setFile(null)}
                style={{ background:'none', border:'none', cursor:'pointer', color:'#94a3b8', display:'flex', flexShrink:0 }}>
                <X size={12} />
              </button>
            </div>
          ) : (
            <button className="btn-outline" style={{ borderStyle:'dashed' }}
              onClick={() => fileInputRef.current?.click()}>
              <ImageIcon size={13} /> Upload Document
            </button>
          )}
          <input type="file" ref={fileInputRef} style={{ display:'none' }}
            accept=".pdf,.jpg,.jpeg,.png" onChange={handleFile} />

          {/* Mode pill — only shown when result is available */}
          {result && (
            <div className="mode-pill">
              {MODES.map(m => {
                const Icon = m.icon;
                return (
                  <button key={m.id} className={`mode-btn ${mode === m.id ? 'active' : ''}`}
                    onClick={() => setMode(m.id)}>
                    <Icon size={12} /> {m.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          {/* Language toggle */}
          <div style={{ display:'flex', alignItems:'center', gap:7, cursor:'pointer', userSelect:'none' }}
            onClick={() => !processing && setMarathi(!marathi)}>
            <div style={{ width:36, height:20, borderRadius:10, background: marathi ? '#0f172a' : '#cbd5e1', position:'relative', transition:'.25s' }}>
              <div style={{ width:14, height:14, background:'white', borderRadius:'50%', position:'absolute', top:3, left: marathi ? 19 : 3, transition:'.25s', boxShadow:'0 1px 3px rgba(0,0,0,.15)' }} />
            </div>
            <span style={{ fontSize:12, fontWeight:600, color:'#334155' }}>{marathi ? 'मराठी OCR' : 'English OCR'}</span>
          </div>
          <div style={{ width:1, height:18, background:'#e2e8f0' }} />
          <button className="btn-primary" onClick={handleExtract} disabled={!file || processing}>
            {processing ? <><span className="spin">◌</span> Extracting…</> : '▶  Extract'}
          </button>
        </div>
      </div>

      <div className="main-wrap">

        {/* ── Left Panel ── */}
        <div className="left-panel">
          <div className="panel-body">

            {/* Thumbnail */}
            {currentImg ? (
              <div>
                <div style={{ fontSize:10, fontWeight:700, color:'#94a3b8', textTransform:'uppercase', letterSpacing:'.5px', marginBottom:8 }}>
                  Document Preview
                </div>
                <div className="thumb-wrap">
                  <img src={currentImg} alt="Page Preview" />
                  <div className="page-badge">Page {pageIndex + 1} / {pageCount}</div>
                </div>
                {pageCount > 1 && (
                  <div style={{ display:'flex', gap:6, marginTop:8 }}>
                    <button className="btn-outline" style={{ flex:1, height:28, fontSize:11 }}
                      onClick={() => changePage(Math.max(0, pageIndex - 1))}
                      disabled={pageIndex === 0}>← Prev</button>
                    <button className="btn-outline" style={{ flex:1, height:28, fontSize:11 }}
                      onClick={() => changePage(Math.min(pageCount - 1, pageIndex + 1))}
                      disabled={pageIndex === pageCount - 1}>Next →</button>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ background:'#f8fafc', border:'2px dashed #e2e8f0', borderRadius:10, height:220, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color:'#94a3b8' }}>
                <ImageIcon size={26} style={{ opacity:.35, marginBottom:8 }} />
                <span style={{ fontSize:11, fontWeight:500 }}>No preview</span>
              </div>
            )}

            {/* Stats */}
            {result && (
              <motion.div initial={{ opacity:0, y:6 }} animate={{ opacity:1, y:0 }} className="stat-grid">
                <StatCard label="Words"    value={wordCount.toLocaleString()} />
                <StatCard label="Time"     value={ocrTimeStr} sub={totalTimeStr} />
                <StatCard label="Lines"    value={lineCount.toLocaleString()} />
                <StatCard label="Pipeline" value={fromCache ? 'OCR ⚡' : 'OCR'} sub={fromCache ? 'from cache' : 'layer1_positional'} />
              </motion.div>
            )}

            {/* Mode description */}
            {result && (
              <div style={{ background:'#f8fafc', border:'1px solid #e2e8f0', borderRadius:9, padding:'10px 12px', fontSize:11, color:'#64748b', lineHeight:1.5 }}>
                <div style={{ fontWeight:700, color:'#334155', marginBottom:4 }}>
                  {currentMode.id === 'flow' && '📄 Flow Mode'}
                  {currentMode.id === 'positional' && '📐 Positional Mode'}
                  {currentMode.id === 'exact' && '🔬 Exact Mode'}
                </div>
                {currentMode.id === 'flow' && 'Plain reading-order text. Each OCR line on its own row.'}
                {currentMode.id === 'positional' && 'X coordinates → character positions. Columns emerge naturally from spacing. No table engine used.'}
                {currentMode.id === 'exact' && 'Every word placed at its real pixel position over the page image.'}
              </div>
            )}

          </div>
        </div>

        {/* ── Workspace ── */}
        <div className="workspace" ref={containerRef}>

          {/* Floating actions */}
          {result && (
            <div className="fabs">
              <button className="fab" onClick={async () => {
                try {
                  await navigator.clipboard.writeText(cleanText);
                } catch {
                  const textarea = document.createElement("textarea");
                  textarea.value = cleanText;
                  document.body.appendChild(textarea);
                  textarea.select();
                  document.execCommand("copy");
                  document.body.removeChild(textarea);
                }
              }}>
                <Copy size={15} /><span className="tip">Copy Text</span>
              </button>
              <button className="fab" onClick={() => {
                const blob = new Blob([cleanText], { type: "text/plain" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${file?.name || 'document'}.txt`;
                a.click();
                URL.revokeObjectURL(url);
              }}>
                <Download size={15} /><span className="tip">Export Text</span>
              </button>
            </div>
          )}

          {/* Zoom toolbar */}
          <div className="zoom-bar">
            <button className="z-btn" onClick={() => setZoom(z => Math.max(40, z - 10))}><ZoomOut size={13} /></button>
            <div className="z-val">{zoom}%</div>
            <button className="z-btn" onClick={() => setZoom(z => Math.min(200, z + 10))}><ZoomIn size={13} /></button>
            <button className="z-btn" onClick={() => setZoom(100)}><Maximize size={11} /></button>
          </div>

          {/* Paper */}
          <div className="paper-wrap" style={{ transform:`scale(${zoom / 100})` }}>
            <div className="paper">

              {/* Processing */}
              {processing && (
                <div style={{ position:'absolute', inset:0, background:'rgba(255,255,255,.92)', zIndex:50, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', borderRadius:14 }}>
                  <div className="scan-line" />
                  <div style={{ width:340 }}>
                    <div style={{ fontSize:16, fontWeight:700, color:'#0f172a', textAlign:'center', marginBottom:6 }}>Extracting Document…</div>
                    <div style={{ fontSize:12, color:'#6366f1', fontWeight:600, textAlign:'center', marginBottom:24, minHeight:16 }}>{statusMsg}</div>
                    {[100, 80, 94, 65, 100, 74].map((w, i) => (
                      <div key={i} className="skel" style={{ width:`${w}%` }} />
                    ))}
                  </div>
                </div>
              )}

              {/* Empty */}
              {!processing && !result && (
                <div className="empty">
                  <FileText size={52} style={{ opacity:.15 }} />
                  <div className="empty-title">Workspace Ready</div>
                  <div className="empty-sub">Upload a document and press Extract</div>
                </div>
              )}

              {/* Result */}
              {!processing && result && (
                <motion.div initial={{ opacity:0 }} animate={{ opacity:1 }}>

                  {/* Paper header */}
                  <div className="paper-hdr">
                    <div>
                      <div className="paper-title">Scanned Document</div>
                      <div className="paper-sub">
                        {lineCount} lines · {wordCount} words · Page {pageIndex + 1} of {pageCount}
                      </div>
                    </div>
                    <div className={`badge ${currentMode.badge}`}>
                      {currentMode.id === 'flow'       && '▤ Flow'}
                      {currentMode.id === 'positional' && '⊞ Positional'}
                      {currentMode.id === 'exact'      && '⊕ Exact Layout'}
                    </div>
                  </div>

                  {/* Renderers */}
                  {mode === 'flow'       && <FlowRenderer        lines={pageLines} />}
                  {mode === 'positional' && <PositionalRenderer   lines={pageLines} />}
                  {mode === 'exact'      && (
                    <ExactRenderer
                      lines={pageLines}
                      pageImg={currentImg}
                      pageDims={pageDims}
                    />
                  )}

                  {pageLines.length === 0 && (
                    <div style={{ color:'#94a3b8', fontSize:14, padding:'40px 0', textAlign:'center' }}>
                      No text detected on this page.
                    </div>
                  )}

                </motion.div>
              )}

            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
