import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { apiGetUsers, apiGetUserFresh } from '../api/api';

const DEFAULT_CTX = {
  users: [], setUsers: () => {}, loading: true,
  error: null, loadData: async () => {}, refreshUser: async () => {},
  autoUpdated: false, lastSyncTime: null, syncError: null,
};

const DataContext = createContext(DEFAULT_CTX);

// Map Supabase user record → frontend expected shape
function mapUser(u) {
  // The backend list_users returns:
  //   u.aadhaar = { name, aadhaar_number, dob, confidence }  ← OCR sub-object
  //   u.pan     = { name, pan_number,     dob, confidence }  ← OCR sub-object
  //   u.aadhaar_number = flat alias from extracted_data
  //   u.pan_number     = flat alias from extracted_data
  //   u.doc_types      = sorted array of doc types from documents table
  //                      e.g. ['aadhaar', 'pan', 'tenth', 'twelfth', 'degree']

  // NEVER overwrite the aadhaar/pan sub-objects with flat strings.
  // The KYCComparisonSection and DocBadges read user.aadhaar.aadhaar_number.
  const aadhaarObj = (u.aadhaar && typeof u.aadhaar === 'object') ? u.aadhaar : {};
  const panObj     = (u.pan     && typeof u.pan     === 'object') ? u.pan     : {};

  return {
    ...u,
    // Name: strictly from user-entered full_name
    name:          u.full_name || u.name || '',
    original_name: u.full_name || u.original_name || '',
    // Preserve aadhaar/pan as objects (never replace with strings)
    aadhaar:       aadhaarObj,
    pan:           panObj,
    // Flat alias strings for backward compat (card table display)
    aadhaar_number: u.aadhaar_number || aadhaarObj.aadhaar_number || '',
    pan_number:     u.pan_number     || panObj.pan_number         || '',
    // ── User-entered ID numbers from the onboarding form ──────────────────────
    // These come from users.aadhaar_number / users.pan_number
    // and are SEPARATE from OCR-extracted values (aadhaar.aadhaar_number, etc.).
    // KYCComparisonSection reads these for the "User Entered" column.
    entered_aadhaar_number: u.entered_aadhaar_number || '',
    entered_pan_number:     u.entered_pan_number     || '',
    // doc_types: array from documents table — drives DocBadges
    doc_types:     u.doc_types || [],
    // DOB
    extracted_dob: u.extracted_dob || '',
    // Confidence (0-100 percentage from backend)
    confidence:    u.confidence ?? u.confidence_score ?? 0,
  };
}

export function DataProvider({ children }) {
  const [users, setUsers]     = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [autoUpdated]         = useState(false);
  const [lastSyncTime]        = useState(null);
  const [syncError]           = useState(null);

  const loadData = useCallback(async (force = false) => {
    if (!force && users.length > 0) {
      console.log('[DataContext] Using cached dataset, size:', users.length);
      return;
    }
    setLoading(true);
    setError(null);
    console.log('[DataContext] Fetching /api/users...');
    try {
      const data = await apiGetUsers(500, 0);
      const rows = (data.users || []).map(mapUser).sort((a, b) => a.id - b.id);
      console.log(`[DataContext] Loaded ${rows.length} users from /api/users`);
      setUsers(rows);
    } catch (err) {
      console.error('[DataContext] API Error:', err.message);
      setError('Failed to connect to the server. Please check your connection.');
    } finally {
      setLoading(false);
    }
  }, [users.length]);

  /**
   * Fetch fresh OCR data for a single user and merge it into the users array.
   * Called per-user during bulk OCR polling (via recently_completed list).
   * This prevents the expensive full-table reload for every completed batch.
   */
  const refreshUser = useCallback(async (userId) => {
    try {
      const data = await apiGetUserFresh(userId);
      if (data?.success && data.user) {
        const fresh = mapUser(data.user);
        setUsers(prev => prev.map(u => u.id === userId ? fresh : u));
        return fresh;
      }
    } catch (err) {
      console.warn('[DataContext] refreshUser failed for', userId, err.message);
    }
    return null;
  }, []);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <DataContext.Provider value={{ users, setUsers, loading, error, loadData, refreshUser, autoUpdated, lastSyncTime, syncError }}>
      {children}
    </DataContext.Provider>
  );
}

export function useData() {
  const ctx = useContext(DataContext);
  if (!ctx) {
    console.warn('[useData] Called outside DataProvider — returning defaults');
    return DEFAULT_CTX;
  }
  return ctx;
}
