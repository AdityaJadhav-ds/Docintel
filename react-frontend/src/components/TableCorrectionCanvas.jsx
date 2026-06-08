import React, { useState, useRef, useMemo, useEffect } from 'react';
import { MousePointer2, Scissors, Link, Maximize2, GitMerge } from 'lucide-react';

export default function TableCorrectionCanvas({ blocks, layoutMeta, pageImages, pageDims, onMutate, onSelectBlock, selectedBlockId: externalSelectedId }) {
  const containerRef = useRef(null);
  const [selectedIds, setSelectedIds] = useState([]);
  const [activeTool, setActiveTool] = useState('select');
  const [debugMode, setDebugMode] = useState(true);

  // Sync single-select to parent sidebar
  useEffect(() => {
    if (selectedIds.length === 1) onSelectBlock?.(selectedIds[0]);
    else if (selectedIds.length === 0) onSelectBlock?.(null);
  }, [selectedIds, onSelectBlock]);

  // Constants for rendering scale
  const RENDER_W = 900;
  const pageW = pageDims?.width || 794;
  const pageH = pageDims?.height || 1123;
  const RENDER_H = Math.round(RENDER_W * (pageH / pageW));
  
  const previewSrc = pageImages[0] || null;

  // Handle Box Click
  const handleBoxClick = (e, b) => {
    e.stopPropagation();
    const bid = b.id || b.node_id;
    
    if (activeTool === 'select') {
      if (e.shiftKey || e.metaKey) {
        if (selectedIds.includes(bid)) setSelectedIds(selectedIds.filter(id => id !== bid));
        else setSelectedIds([...selectedIds, bid]);
      } else {
        setSelectedIds([bid]);
      }
    } else if (activeTool === 'split') {
      // Calculate relative X split point
      const rect = e.currentTarget.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const normalizedSplitX = b.nx1 + ((clickX / rect.width) * (b.nx2 - b.nx1));
      
      // We must pass actual pixel coordinates to split_row because the backend right now uses `split_x` relative to actual pixels.
      // Wait, let's pass both so the backend can use it.
      const pixelSplitX = normalizedSplitX * pageW;
      
      onMutate('split_row', { block_id: bid, split_x: pixelSplitX });
      setActiveTool('select');
    }
  };

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'm' && selectedIds.length >= 2) {
         // Perform Merge
         const source = selectedIds[1];
         const target = selectedIds[0];
         onMutate('merge_row', { source_id: source, target_id: target });
         setSelectedIds([]);
      }
      if (e.key === 'Escape') {
         setSelectedIds([]);
         setActiveTool('select');
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [selectedIds, onMutate]);

  // Render Connections / Visual Debugger
  const renderLinks = () => {
    if (!debugMode) return null;
    const links = layoutMeta?.links || [];
    
    // Map block centers
    const centers = {};
    blocks.forEach(b => {
       const bid = b.id || b.node_id;
       centers[bid] = {
          x: (b.nx1 + (b.nx2 - b.nx1) / 2) * RENDER_W,
          y: (b.ny1 + (b.ny2 - b.ny1) / 2) * RENDER_H
       };
    });
    
    return (
      <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 10 }}>
         {links.map((lk, i) => {
            const s = centers[lk.source];
            const t = centers[lk.target];
            if (!s || !t) return null;
            return (
               <g key={i}>
                 <line x1={s.x} y1={s.y} x2={t.x} y2={t.y} stroke="rgba(99,102,241,0.5)" strokeWidth="2" strokeDasharray="4 4" />
                 <circle cx={t.x} cy={t.y} r="3" fill="#6366f1" />
               </g>
            );
         })}
      </svg>
    );
  };

  return (
    <div style={{ padding: 40, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
      
      {/* Top Toolbar */}
      <div style={{
          display: 'flex', gap: 10, background: 'white', padding: '8px 16px', 
          borderRadius: 8, boxShadow: '0 2px 10px rgba(0,0,0,0.05)', marginBottom: 20
      }}>
         <button onClick={() => setActiveTool('select')} style={btnStyle(activeTool === 'select')} title="Select (V)"><MousePointer2 size={16} /> Select</button>
         <button onClick={() => setActiveTool('split')} style={btnStyle(activeTool === 'split')} title="Split Tool (S)"><Scissors size={16} /> Split Cell</button>
         <button onClick={() => setDebugMode(!debugMode)} style={btnStyle(debugMode)}><Maximize2 size={16} /> Graph Debugger</button>
         
         <div style={{ width: 1, background: '#e5e7eb', margin: '0 8px' }} />
         
         <button 
           disabled={selectedIds.length < 2} 
           onClick={() => {
              onMutate('merge_row', { source_id: selectedIds[1], target_id: selectedIds[0] });
              setSelectedIds([]);
           }}
           style={{ ...btnStyle(false), opacity: selectedIds.length < 2 ? 0.4 : 1, color: '#4f46e5' }}
         >
           <GitMerge size={16} /> Merge Selected (M)
         </button>
      </div>

      {/* Canvas */}
      <div ref={containerRef} style={{ width: RENDER_W, height: RENDER_H, position: 'relative', background: 'white', boxShadow: '0 8px 30px rgba(0,0,0,0.1)' }}>
        {previewSrc && <img src={previewSrc} alt="" style={{ position: 'absolute', width: '100%', height: '100%', objectFit: 'contain', opacity: 0.15 }} />}
        
        {renderLinks()}

        {blocks.map((b) => {
          const bid = b.id || b.node_id;
          const isSelected = selectedIds.includes(bid);
          const isPending = b._status === 'pending';
          
          let borderColor = isSelected ? '#3b82f6' : 'rgba(107,114,128,0.3)';
          let bgColor = isSelected ? 'rgba(59,130,246,0.1)' : 'rgba(255,255,255,0.8)';
          
          if (isPending) {
             borderColor = '#f59e0b';
             bgColor = 'rgba(245,158,11,0.2)';
          }

          return (
            <div 
              key={bid}
              onClick={(e) => handleBoxClick(e, b)}
              style={{
                position: 'absolute',
                left: `${(b.nx1 || 0) * 100}%`,
                top: `${(b.ny1 || 0) * 100}%`,
                width: `${((b.nx2 || 0) - (b.nx1 || 0)) * 100}%`,
                height: `${((b.ny2 || 0) - (b.ny1 || 0)) * 100}%`,
                border: `2px solid ${borderColor}`,
                background: bgColor,
                cursor: activeTool === 'split' ? 'crosshair' : 'pointer',
                transition: 'all 0.1s ease',
                display: 'flex', alignItems: 'flex-start',
                overflow: 'hidden', padding: 2,
                fontSize: 10,
                color: '#1f2937',
                zIndex: isSelected ? 20 : 1
              }}
            >
              {debugMode && (
                <div style={{ position: 'absolute', top: 0, right: 0, background: '#3b82f6', color: 'white', fontSize: 8, padding: '0 4px', fontWeight: 'bold' }}>
                  {b.reading_order_index}
                </div>
              )}
              {b.corrected_text || b.text}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function btnStyle(active) {
  return {
    display: 'flex', alignItems: 'center', gap: 6,
    padding: '6px 12px', border: 'none', borderRadius: 6,
    background: active ? '#eef2ff' : 'transparent',
    color: active ? '#4f46e5' : '#4b5563',
    fontWeight: 600, fontSize: 12, cursor: 'pointer',
    transition: '0.2s'
  };
}
