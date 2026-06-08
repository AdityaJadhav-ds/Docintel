/* ReviewDocumentViewer — white light-theme document preview */

import { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import { getApiBase } from '../api/api';
import {
  ZoomIn, ZoomOut, RotateCw, Maximize2, RefreshCw,
  Download, FileText, ImageIcon, AlertCircle,
} from 'lucide-react';

/* ── loading skeleton ───────────────────────────────────── */
function DocSkeleton() {
  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 14, padding: 32,
    }}>
      <div style={{
        width: 56, height: 72, borderRadius: 8,
        background: '#e5e7eb',
        animation: 'shimmer 1.4s ease-in-out infinite',
        position: 'relative',
      }}>
        <div style={{
          position: 'absolute', top: 6, right: -4, width: 16, height: 16,
          background: '#f3f4f6', borderRadius: '0 4px 0 0',
        }} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center' }}>
        <div style={{ height: 8, width: 120, borderRadius: 4, background: '#e5e7eb', animation: 'shimmer 1.4s ease-in-out infinite' }} />
        <div style={{ height: 6, width: 80, borderRadius: 4, background: '#f3f4f6', animation: 'shimmer 1.4s ease-in-out infinite 0.2s' }} />
      </div>
      <p style={{ fontSize: 13, color: '#9ca3af', margin: 0 }}>Loading preview…</p>
    </div>
  );
}

/* ── toolbar button ─────────────────────────────────────── */
function ToolBtn({ onClick, title, children, active }) {
  return (
    <button
      onClick={onClick}
      title={title}
      style={{
        width: 30, height: 30, borderRadius: 6,
        background: active ? '#eff6ff' : 'transparent',
        border: active ? '1px solid #bfdbfe' : '1px solid transparent',
        color: active ? '#2563eb' : '#6b7280',
        cursor: 'pointer',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        transition: 'all 0.12s ease',
      }}
      onMouseEnter={e => {
        if (!active) { e.currentTarget.style.background = '#f9fafb'; e.currentTarget.style.color = '#374151'; }
      }}
      onMouseLeave={e => {
        if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#6b7280'; }
      }}
    >
      {children}
    </button>
  );
}

/* ══════════════════════════════════════════════════════════ */
export default function ReviewDocumentViewer({ doc, docType, label }) {
  const [url, setUrl]         = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [retry, setRetry]     = useState(0);
  const [zoom, setZoom]       = useState(1);
  const [rotation, setRotation] = useState(0);
  const [imgErr, setImgErr]   = useState(false);
  const apiBase = getApiBase();

  const isPdf = doc?.file_type === 'pdf'
    || doc?.storage_path?.toLowerCase().endsWith('.pdf')
    || doc?.file_name?.toLowerCase().endsWith('.pdf');

  /* ── fetch URL ─────────────────────────────────────────── */
  const load = useCallback(async () => {
    if (!doc) { setLoading(false); return; }
    setLoading(true); setError(null); setImgErr(false);

    // 1. Already have a URL and not retrying — use it directly
    const candidate = doc.signed_url || doc.preview_url;
    if (candidate && retry === 0) {
      setUrl(candidate); setLoading(false); return;
    }

    // 2. Fetch fresh URL
    let fresh = null;
    if (doc.id) {
      try {
        const r = await axios.get(`${apiBase}/documents/${doc.id}/preview-url`, { timeout: 8000 });
        fresh = r.data?.signed_url;
      } catch (_) {}
    }
    if (!fresh && doc.storage_path) {
      try {
        const r = await axios.get(`${apiBase}/signed-url`, {
          params: { storage_path: doc.storage_path, expires_in: 7200 },
          timeout: 8000,
        });
        fresh = r.data?.signed_url;
      } catch (_) {}
    }

    if (fresh) setUrl(fresh);
    else setError('Could not generate a preview URL. Check Supabase storage permissions.');
    setLoading(false);
  }, [doc, retry, apiBase]);

  useEffect(() => { load(); }, [load]);

  const handleZoom = (d) => setZoom(z => Math.max(0.25, Math.min(4, +(z + d).toFixed(2))));
  const handleDownload = () => {
    if (!url) return;
    const a = document.createElement('a');
    a.href = url; a.download = doc?.file_name || `${docType}_doc`;
    a.click();
  };

  /* ── empty state ─────────────────────────────────────────*/
  if (!doc && !loading) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 12, padding: 32,
      }}>
        <div style={{
          width: 56, height: 56, borderRadius: 14, background: '#f3f4f6',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <FileText size={24} color="#d1d5db" />
        </div>
        <p style={{ fontSize: 13, color: '#9ca3af', margin: 0, textAlign: 'center' }}>
          No {label} uploaded yet
        </p>
      </div>
    );
  }

  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      background: '#ffffff', borderRadius: 12,
      border: '1px solid #e5e7eb',
      boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
      overflow: 'hidden',
    }}>
      {/* ── Viewer toolbar ─────────────────────────────────── */}
      <div style={{
        height: 44, padding: '0 12px',
        borderBottom: '1px solid #f3f4f6',
        background: '#fafafa',
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        {/* left: doc info */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {isPdf
            ? <FileText  size={14} color="#6b7280" />
            : <ImageIcon size={14} color="#6b7280" />
          }
          <span style={{ fontSize: 12.5, fontWeight: 500, color: '#374151' }}>
            {label}
          </span>
          {doc?.file_name && (
            <span style={{ fontSize: 11.5, color: '#9ca3af', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              · {doc.file_name}
            </span>
          )}
        </div>

        {/* right: controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
          <ToolBtn onClick={() => handleZoom(-0.15)} title="Zoom out"><ZoomOut size={13} /></ToolBtn>
          <span style={{ fontSize: 11.5, color: '#9ca3af', minWidth: 38, textAlign: 'center', fontWeight: 600 }}>
            {Math.round(zoom * 100)}%
          </span>
          <ToolBtn onClick={() => handleZoom(0.15)} title="Zoom in"><ZoomIn size={13} /></ToolBtn>
          {!isPdf && (
            <ToolBtn onClick={() => setRotation(r => (r + 90) % 360)} title="Rotate">
              <RotateCw size={13} />
            </ToolBtn>
          )}
          <div style={{ width: 1, height: 18, background: '#e5e7eb', margin: '0 4px' }} />
          <ToolBtn onClick={() => url && window.open(url, '_blank')} title="Open in new tab">
            <Maximize2 size={13} />
          </ToolBtn>
          {url && <ToolBtn onClick={handleDownload} title="Download"><Download size={13} /></ToolBtn>}
          <ToolBtn onClick={() => setRetry(n => n + 1)} title="Refresh preview">
            <RefreshCw size={13} style={{ animation: loading ? 'spin 0.8s linear infinite' : 'none' }} />
          </ToolBtn>
        </div>
      </div>

      {/* ── Viewer canvas ───────────────────────────────────── */}
      <div style={{
        flex: 1, overflow: 'auto',
        background: '#f8fafc',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: 20,
        position: 'relative',
      }}>
        {loading && <DocSkeleton />}

        {!loading && error && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center', maxWidth: 280 }}>
            <div style={{
              width: 48, height: 48, borderRadius: 12, background: '#fef2f2',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <AlertCircle size={22} color="#dc2626" />
            </div>
            <div>
              <p style={{ fontSize: 14, fontWeight: 600, color: '#111827', margin: '0 0 6px' }}>Preview unavailable</p>
              <p style={{ fontSize: 12.5, color: '#6b7280', margin: 0, lineHeight: 1.6 }}>{error}</p>
            </div>
            <button
              onClick={() => setRetry(n => n + 1)}
              style={{
                padding: '7px 16px', borderRadius: 8, border: '1px solid #e5e7eb',
                background: '#fff', fontSize: 13, fontWeight: 500, color: '#374151',
                cursor: 'pointer',
              }}
            >
              Try again
            </button>
          </div>
        )}

        {!loading && !error && url && !imgErr && (
          isPdf ? (
            <iframe
              src={url}
              title={label}
              style={{
                width: `${zoom * 100}%`,
                height: '100%', minHeight: 400,
                border: 'none', borderRadius: 6,
                boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
              }}
            />
          ) : (
            <img
              src={url}
              alt={label}
              onError={() => {
                setImgErr(true);
                if (retry < 2) setRetry(n => n + 1);
                else setError('Image could not be displayed. The URL may have expired.');
              }}
              style={{
                maxWidth: '100%', maxHeight: '100%',
                objectFit: 'contain',
                transform: `scale(${zoom}) rotate(${rotation}deg)`,
                transformOrigin: 'center center',
                transition: 'transform 0.2s ease',
                borderRadius: 6,
                boxShadow: '0 4px 16px rgba(0,0,0,0.10)',
                background: '#fff',
              }}
            />
          )
        )}
      </div>

      {/* ── Status footer ───────────────────────────────────── */}
      {url && !loading && (
        <div style={{
          height: 32, padding: '0 14px',
          borderTop: '1px solid #f3f4f6',
          background: '#fafafa',
          display: 'flex', alignItems: 'center', gap: 6,
          flexShrink: 0,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#16a34a' }} />
          <span style={{ fontSize: 11.5, color: '#9ca3af', fontWeight: 500 }}>Preview loaded</span>
          {doc?.file_size && (
            <span style={{ fontSize: 11.5, color: '#d1d5db', marginLeft: 'auto' }}>
              {(doc.file_size / 1024).toFixed(0)} KB
            </span>
          )}
        </div>
      )}
    </div>
  );
}
