import { useState, useEffect, useCallback, useRef } from 'react';
import {
  ZoomIn, ZoomOut, RotateCw, Maximize2, RefreshCw,
  Download, FileText, Image, AlertCircle, ChevronLeft, ChevronRight, Eye
} from 'lucide-react';
import axios from 'axios';
import { getApiBase } from '../api/api';

function LoadingSkeleton() {
  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, padding: 32 }}>
      <div style={{ width: 64, height: 64, borderRadius: 16, background: 'linear-gradient(135deg, #1e293b, #334155)', display: 'flex', alignItems: 'center', justifyContent: 'center', animation: 'pulse 1.5s ease-in-out infinite' }}>
        <FileText size={28} color="#94a3b8" />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'center' }}>
        <div style={{ height: 10, width: 140, borderRadius: 6, background: '#1e293b', animation: 'shimmer 1.4s ease-in-out infinite' }} />
        <div style={{ height: 8, width: 100, borderRadius: 6, background: '#1e293b', animation: 'shimmer 1.4s ease-in-out infinite 0.2s' }} />
      </div>
      <p style={{ fontSize: 13, color: '#64748b', margin: 0 }}>Loading document preview…</p>
    </div>
  );
}

export default function DocumentViewer({ doc, docType, label }) {
  const [url, setUrl] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [imgError, setImgError] = useState(false);
  const containerRef = useRef(null);
  const apiBase = getApiBase();

  const isPdf = doc?.file_type === 'pdf' || doc?.storage_path?.toLowerCase().endsWith('.pdf') ||
                doc?.file_name?.toLowerCase().endsWith('.pdf');

  const fetchSignedUrl = useCallback(async () => {
    if (!doc) { setLoading(false); return; }

    setLoading(true);
    setError(null);
    setImgError(false);

    // Try doc.signed_url first
    const candidateUrls = [
      doc.signed_url,
      doc.preview_url,
    ].filter(Boolean);

    // If we have a candidate, use it directly
    if (candidateUrls.length > 0 && retryCount === 0) {
      setUrl(candidateUrls[0]);
      setLoading(false);
      return;
    }

    // Otherwise fetch a fresh signed URL from the backend
    try {
      let freshUrl = null;

      // Try /documents/{doc_id}/preview-url
      if (doc.id) {
        try {
          const res = await axios.get(`${apiBase}/documents/${doc.id}/preview-url`, { timeout: 8000 });
          freshUrl = res.data?.signed_url;
        } catch (_) {}
      }

      // Fallback: try /signed-url?storage_path=...
      if (!freshUrl && doc.storage_path) {
        try {
          const res = await axios.get(`${apiBase}/signed-url`, {
            params: { storage_path: doc.storage_path, expires_in: 7200 },
            timeout: 8000
          });
          freshUrl = res.data?.signed_url;
        } catch (_) {}
      }

      if (freshUrl) {
        setUrl(freshUrl);
      } else {
        setError('Could not load document preview. Please check storage permissions.');
      }
    } catch (err) {
      setError(`Preview load failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  }, [doc, retryCount, apiBase]);

  useEffect(() => {
    fetchSignedUrl();
  }, [fetchSignedUrl]);

  const handleRetry = () => {
    setRetryCount(c => c + 1);
    setUrl(null);
  };

  const handleZoom = (delta) => setZoom(z => Math.max(0.3, Math.min(4, z + delta)));
  const handleRotate = () => setRotation(r => (r + 90) % 360);
  const handleFullscreen = () => {
    if (url) window.open(url, '_blank');
  };
  const handleDownload = () => {
    if (url) {
      const a = document.createElement('a');
      a.href = url;
      a.download = doc?.file_name || `${docType}_document`;
      a.click();
    }
  };

  const typeColor = docType === 'aadhaar' ? '#10b981' : '#6366f1';
  const typeBg    = docType === 'aadhaar' ? 'rgba(16,185,129,0.1)' : 'rgba(99,102,241,0.1)';

  return (
    <div style={{
      background: '#0f172a',
      border: '1px solid #1e293b',
      borderRadius: 16,
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      height: '100%',
      position: 'relative',
    }}>
      {/* Viewer Header */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #1e293b',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        background: '#0f172a',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: typeBg,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {isPdf ? <FileText size={15} color={typeColor} /> : <Image size={15} color={typeColor} />}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', letterSpacing: '0.01em' }}>{label}</div>
            <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>
              {isPdf ? 'PDF Document' : 'Image'} {doc?.file_name ? `· ${doc.file_name}` : ''}
            </div>
          </div>
        </div>

        {/* Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <button onClick={() => handleZoom(-0.2)} title="Zoom Out" style={ctrlBtn}>
            <ZoomOut size={14} />
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8', minWidth: 36, textAlign: 'center', fontWeight: 600 }}>
            {Math.round(zoom * 100)}%
          </span>
          <button onClick={() => handleZoom(0.2)} title="Zoom In" style={ctrlBtn}>
            <ZoomIn size={14} />
          </button>
          {!isPdf && (
            <button onClick={handleRotate} title="Rotate" style={ctrlBtn}>
              <RotateCw size={14} />
            </button>
          )}
          <div style={{ width: 1, height: 20, background: '#1e293b', margin: '0 2px' }} />
          <button onClick={handleFullscreen} title="Open in new tab" style={ctrlBtn}>
            <Maximize2 size={14} />
          </button>
          {url && (
            <button onClick={handleDownload} title="Download" style={ctrlBtn}>
              <Download size={14} />
            </button>
          )}
          <button onClick={handleRetry} title="Refresh" style={ctrlBtn}>
            <RefreshCw size={14} style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          </button>
        </div>
      </div>

      {/* Viewer Body */}
      <div ref={containerRef} style={{
        flex: 1,
        overflow: 'auto',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #0a0f1e 0%, #0f172a 100%)',
        position: 'relative',
        padding: 16,
      }}>
        {loading && <LoadingSkeleton />}

        {!loading && error && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: 32, textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: 'rgba(239,68,68,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <AlertCircle size={24} color="#ef4444" />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', marginBottom: 6 }}>Preview Unavailable</div>
              <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.6, maxWidth: 260 }}>{error}</div>
            </div>
            <button onClick={handleRetry} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 18px', borderRadius: 8,
              background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)',
              color: '#818cf8', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}>
              <RefreshCw size={14} /> Retry Preview
            </button>
          </div>
        )}

        {!loading && !error && !doc && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, padding: 32, textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: '#1e293b', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <FileText size={24} color="#475569" />
            </div>
            <div style={{ fontSize: 13, color: '#64748b' }}>No document uploaded</div>
          </div>
        )}

        {!loading && !error && url && !imgError && (
          isPdf ? (
            <iframe
              src={url}
              title={label}
              style={{
                width: `${zoom * 100}%`,
                height: '100%',
                border: 'none',
                borderRadius: 8,
                minHeight: 420,
                boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
              }}
            />
          ) : (
            <img
              src={url}
              alt={label}
              onError={() => {
                setImgError(true);
                // Auto-retry by fetching fresh URL
                if (retryCount < 2) handleRetry();
                else setError('Image could not be displayed. The URL may have expired.');
              }}
              style={{
                maxWidth: '100%',
                maxHeight: '100%',
                objectFit: 'contain',
                transform: `scale(${zoom}) rotate(${rotation}deg)`,
                transformOrigin: 'center center',
                transition: 'transform 0.25s ease',
                borderRadius: 8,
                boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
              }}
            />
          )
        )}

        {!loading && !error && url && imgError && (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16, padding: 32, textAlign: 'center' }}>
            <div style={{ width: 56, height: 56, borderRadius: 14, background: 'rgba(245,158,11,0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <AlertCircle size={24} color="#f59e0b" />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#f1f5f9', marginBottom: 6 }}>Image Load Error</div>
              <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.6 }}>
                The image could not be rendered. URL may have expired.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={handleRetry} style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 16px', borderRadius: 8,
                background: 'rgba(99,102,241,0.15)', border: '1px solid rgba(99,102,241,0.3)',
                color: '#818cf8', fontSize: 13, fontWeight: 600, cursor: 'pointer',
              }}>
                <RefreshCw size={14} /> Refresh URL
              </button>
              <a href={url} target="_blank" rel="noreferrer" style={{
                display: 'flex', alignItems: 'center', gap: 8,
                padding: '8px 16px', borderRadius: 8,
                background: 'rgba(16,185,129,0.1)', border: '1px solid rgba(16,185,129,0.2)',
                color: '#34d399', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                textDecoration: 'none',
              }}>
                <Eye size={14} /> Open Direct
              </a>
            </div>
          </div>
        )}
      </div>

      {/* Footer status bar */}
      {url && !loading && (
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid #1e293b',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          background: '#0f172a',
          flexShrink: 0,
        }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: '#64748b', fontWeight: 500 }}>Preview loaded</span>
          {doc?.file_size && (
            <span style={{ fontSize: 11, color: '#475569', marginLeft: 'auto' }}>
              {(doc.file_size / 1024).toFixed(1)} KB
            </span>
          )}
        </div>
      )}
    </div>
  );
}

const ctrlBtn = {
  width: 30, height: 30, borderRadius: 8,
  background: 'rgba(255,255,255,0.05)',
  border: '1px solid rgba(255,255,255,0.08)',
  color: '#94a3b8', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  transition: 'all 0.15s ease',
};
