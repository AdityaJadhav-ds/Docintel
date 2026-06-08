/**
 * useApiStatus.js — Single global connection monitor.
 *
 * DESIGN: Uses window.__apiStatusSingleton to guarantee exactly ONE
 * setInterval exists for the entire app lifetime, even across React
 * hot-module-replacement reloads. Previously, every component that called
 * this hook (Navbar + Database) created its own independent interval,
 * causing duplicate health checks and competing state transitions.
 *
 * Health check: GET /api/health (zero blocking I/O on the backend)
 * Interval: 30 seconds — long enough to never matter during OCR,
 *           short enough to detect genuine backend crashes quickly.
 * Offline threshold: 3 consecutive failures required (~90s) before
 *                    declaring offline — a single slow response is ignored.
 */
import { useState, useEffect } from 'react';
import { discoverBackend } from '../api/api';

const POLL_INTERVAL_MS  = 30_000;   // 30s between checks
const OFFLINE_THRESHOLD = 3;        // consecutive failures to declare offline

// ── Singleton state (persists across HMR reloads via window) ──────────────────
function getSingleton() {
  if (!window.__apiStatusSingleton) {
    window.__apiStatusSingleton = {
      status:           'connecting',
      port:             null,
      consecutiveFails: 0,
      subscribers:      new Set(),
      intervalId:       null,
      checking:         false,    // prevent overlapping checks
    };
  }
  return window.__apiStatusSingleton;
}

function notifyAll(s) {
  getSingleton().subscribers.forEach(cb => cb(s.status, s.port));
}

async function runCheck() {
  const s = getSingleton();
  if (s.checking) return;   // already in flight — skip this tick
  s.checking = true;

  try {
    const result = await discoverBackend();

    if (result.connected) {
      s.consecutiveFails = 0;
      if (s.status !== 'online') {
        console.log('[useApiStatus] Backend online');
        s.status = 'online';
        s.port   = result.port;
        notifyAll(s);
      }
    } else {
      s.consecutiveFails += 1;
      console.warn(`[useApiStatus] Health check failed (${s.consecutiveFails}/${OFFLINE_THRESHOLD})`);
      // Only flip to offline after OFFLINE_THRESHOLD consecutive misses.
      // During bulk OCR the backend is busy but alive — a single timeout is noise.
      if (s.consecutiveFails >= OFFLINE_THRESHOLD && s.status !== 'offline') {
        s.status = 'offline';
        s.port   = null;
        notifyAll(s);
      }
    }
  } catch (_) {
    // discoverBackend never throws — this is a safety net only
  } finally {
    s.checking = false;
  }
}

function ensurePolling() {
  const s = getSingleton();
  if (s.intervalId) return;   // already running
  runCheck();                  // immediate first check
  s.intervalId = setInterval(runCheck, POLL_INTERVAL_MS);
}

// ── React hook ────────────────────────────────────────────────────────────────
export function useApiStatus() {
  const singleton = getSingleton();
  const [status, setStatus] = useState(singleton.status);
  const [port,   setPort  ] = useState(singleton.port);

  useEffect(() => {
    const callback = (newStatus, newPort) => {
      setStatus(newStatus);
      setPort(newPort);
    };
    singleton.subscribers.add(callback);
    ensurePolling();

    // Sync local state in case singleton changed before this mount
    setStatus(singleton.status);
    setPort(singleton.port);

    return () => {
      singleton.subscribers.delete(callback);
      // Do NOT stop the interval — it runs for the lifetime of the page
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { status, port, retry: runCheck };
}
