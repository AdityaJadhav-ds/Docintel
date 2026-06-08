import axios from 'axios';

// Use explicit 127.0.0.1 instead of 'localhost' — on Windows, localhost
// resolves to ::1 (IPv6) first, but Uvicorn binds to IPv4 only by default.
const API_BASE = "http://127.0.0.1:8000/api";

export const getApiBase = () => API_BASE;

export const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,   // 30s for normal API calls
});


function getAxios() {
  return axios.create({ baseURL: "http://127.0.0.1:8000" });
}

export async function discoverBackend() {
  try {
    // Timeout raised to 15s: the /health endpoint now does zero blocking I/O,
    // but under heavy OCR load the TCP stack may still take several seconds
    // to accept the connection. 15s gives comfortable headroom.
    // Note: useApiStatus requires 3 consecutive failures before declaring
    // offline, so a single slow response won't interrupt OCR processing.
    const res = await api.get('/health', { timeout: 15000 });
    if (res && res.data && (res.data.status === 'ok' || res.data.status === 'degraded')) {
      return { connected: true, port: 8000 };
    }
    return { connected: false, port: null };
  } catch (err) {
    return { connected: false, port: null };
  }
}



// ─── Legacy Users (root /users) ───────────────────────────
export async function fetchUsers() {
  const res = await getAxios().get('/users', {
    headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' },
    params: { _t: Date.now() },
  });
  return res.data;
}

export async function forceFreshOCR(userId) {
  const res = await getAxios().get(`/user/${userId}/ocr`);
  return res.data;
}

export async function submitUserAction(userId, action, correctedData) {
  if (action === 'APPROVED') {
    try {
      const res = await api.post('/approve', {
        user_id:    userId,
        name:       correctedData.name    || null,
        aadhaar:    correctedData.aadhaar || null,
        pan:        correctedData.pan     || null,
        dob:        correctedData.dob     || null,
        percentage: correctedData.percentage || null,
        cgpa:       correctedData.cgpa    || null,
        email:      correctedData.email   || null,
        mobile:     correctedData.mobile  || null,
        address:    correctedData.address || null,
      });
      // Return full response so caller can use res.user (canonical DB state)
      return res.data;
    } catch (err) {
      const status = err?.response?.status;
      const rawDetail = err?.response?.data?.detail;
      const detail = (typeof rawDetail === 'object' ? rawDetail?.message : rawDetail) || null;
      if (status === 404) {
        throw new Error(detail || 'User not found. Record may not exist in the database.');
      }
      if (status === 422) {
        throw new Error(detail || 'Invalid data format. Check Aadhaar (12 digits) and PAN (ABCDE1234F).');
      }
      if (status >= 500) {
        throw new Error(detail || 'Server error while saving. Please try again.');
      }
      throw new Error(detail || err.message || 'Approval failed — unknown error.');
    }
  }
  const res = await api.post(`/users/${userId}/action`, {
    action, corrected_data: correctedData,
  });
  return res.data;
}


export async function createUser(data) {
  const res = await getAxios().post('/users', data);
  return res.data;
}

export async function pollUploadStatus(entityId) {
  const res = await getAxios().get(`/upload/status/${entityId}`);
  return res.data;
}

// ─── Legacy Upload ────────────────────────────────────────
export async function uploadDocument(formData) {
  const res = await getAxios().post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

// ─── Query ────────────────────────────────────────────────
export async function runQuery(q) {
  const res = await getAxios().get('/query', { params: { q } });
  return res.data;
}

// ─── Audit ────────────────────────────────────────────────
export async function fetchAuditLogs(params = {}) {
  try {
    const res = await api.get('/audit-logs', { params });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Config ───────────────────────────────────────────────
export async function reloadConfig() {
  const res = await getAxios().post('/config/reload');
  return res.data;
}

// ─── Users Meta ───────────────────────────────────────────
export async function fetchUsersMeta() {
  try {
    const res = await getAxios().get('/users/meta', {
      headers: { 'Cache-Control': 'no-cache', 'Pragma': 'no-cache' },
      params: { _t: Date.now() },
    });
    return res.data;
  } catch {
    return null;
  }
}


// ═══════════════════════════════════════════════════════════════
//  NEW SUPABASE-NATIVE API  (/api/* prefix)
//  All functions below map to routes.py endpoints
// ═══════════════════════════════════════════════════════════════

// helper — unwrap axios errors into readable messages
function apiErr(err) {
  const detail = err?.response?.data?.detail;
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail);
  if (detail) return detail;
  return err?.message || 'Unknown error';
}

// ─── Supabase Users ───────────────────────────────────────

/** POST /api/users */
export async function apiCreateUser(fullName, dob, mobile, email, address) {
  try {
    const res = await api.post('/users', { 
      full_name: fullName, 
      dob,
      mobile_number: mobile || '',
      email: email || '',
      permanent_address: address || ''
    });
    return res.data;          // { status, user_id, user }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/users  (paginated) */
export async function apiGetUsers(limit = 100, offset = 0) {
  try {
    const res = await api.get('/users', { params: { limit, offset, _t: Date.now() } });
    return res.data;          // { status, count, total, users }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/users/:id */
export async function apiGetUser(userId) {
  try {
    const res = await api.get(`/users/${userId}`);
    return res.data;          // { status, user }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/users/:id/fresh
 * Fetch a single user with freshest OCR data, bypassing full table reload.
 * Used for targeted row refresh during/after bulk OCR processing.
 * Returns same shape as list_users() so it can be merged into DataContext.users.
 */
export async function apiGetUserFresh(userId) {
  try {
    const res = await api.get(`/users/${userId}/fresh`, {
      params: { _t: Date.now() },  // prevent stale cache
    });
    return res.data;  // { success, user }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** PATCH /api/users/:id */
export async function apiUpdateUser(userId, fields) {
  try {
    const res = await api.patch(`/users/${userId}`, fields);
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Supabase Document Upload ─────────────────────────────

/**
 * POST /api/upload
 * @param {number} userId
 * @param {'aadhaar'|'pan'} docType
 * @param {File} file  — native Browser File object
 * @param {string} expectedId  — optional Aadhaar/PAN for duplicate check
 */
export async function apiUploadDocument(userId, docType, file, expectedId = '', aadhaarNumber = '', panNumber = '') {
  try {
    const fd = new FormData();
    fd.append('user_id', String(userId));
    fd.append('doc_type', docType);
    fd.append('file', file);
    if (expectedId) fd.append('expected_id', expectedId);
    if (aadhaarNumber) fd.append('aadhaar_number', aadhaarNumber);
    if (panNumber) fd.append('pan_number', panNumber);

    const res = await api.post('/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
    return res.data;          // { status, document_id, version, storage_path, signed_url }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * POST /api/complete-upload
 * Uses a long 120-second timeout because PDF → image conversion + OCR
 * can take 30–90 seconds for real documents. DO NOT lower this.
 * Returns: { user_id, user, documents, extracted, ... }
 */
export async function apiCompleteUpload(payload) {
  try {
    const fd = new FormData();
    fd.append('full_name', payload.fullName);
    fd.append('dob', payload.dob);
    if (payload.aadhaarFile) fd.append('aadhaar_file', payload.aadhaarFile);
    if (payload.panFile)     fd.append('pan_file',     payload.panFile);
    if (payload.aadhaarNumber) fd.append('aadhaar_number', payload.aadhaarNumber);
    if (payload.panNumber)     fd.append('pan_number',     payload.panNumber);
    if (payload.mobile)        fd.append('mobile_number',  payload.mobile);
    if (payload.email)         fd.append('email',          payload.email);
    if (payload.address)       fd.append('permanent_address', payload.address);

    // Do NOT set Content-Type manually — browser must set multipart/form-data
    // with the correct boundary automatically.
    const res = await api.post('/complete-upload', fd, {
      timeout: 120_000,   // 2-minute timeout for PDF OCR pipeline
    });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * POST /api/users/{userId}/documents/upload
 * Upload a single document (ANY type) for an existing candidate.
 * Accepted doc_type: aadhaar | pan | tenth | twelfth | diploma | degree | semester
 * This is the PRIMARY way to link academic docs to a candidate_id.
 */
export async function apiUploadDocumentForUser(userId, docType, file, enteredPercentage = '') {
  try {
    const fd = new FormData();
    fd.append('doc_type', docType);
    fd.append('file', file);
    if (enteredPercentage) fd.append('entered_percentage', String(enteredPercentage));
    const res = await api.post(`/users/${userId}/documents/upload`, fd, {
      timeout: 60_000,
    });
    return res.data;   // { success, document, storage_path, preview_url }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}


/**
 * POST /api/reprocess-ocr/:userId
 * Re-run OCR for all documents of a user. Use when PAN/Aadhaar shows "No data".
 */
export async function apiReprocessOCR(userId) {
  try {
    const res = await api.post(`/reprocess-ocr/${userId}`, null, {
      timeout: 10_000,
    });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/documents/:userId */
export async function apiGetDocuments(userId, docType = null) {
  try {
    const params = docType ? { doc_type: docType } : {};
    const res = await api.get(`/documents/${userId}`, { params });
    return res.data;          // { status, count, documents }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── OCR: Enqueue + Poll + Results ───────────────────────

/**
 * POST /api/run-ocr/:documentId — non-blocking, returns job_id immediately.
 */
export async function apiRunOCR(documentId, force = false) {
  try {
    const res = await api.post(`/run-ocr/${documentId}`, null, { params: { force } });
    return res.data;          // { status, job_id, enqueued, reason }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/ocr-status/:jobId — poll one OCR job.
 * status values: pending → processing → completed | failed
 */
export async function apiGetOCRStatus(jobId) {
  try {
    const res = await api.get(`/ocr-status/${jobId}`);
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/ocr-results/:userId
 */
export async function apiGetOCRResults(userId, docType = null) {
  try {
    const params = docType ? { doc_type: docType } : {};
    const res = await api.get(`/ocr-results/${userId}`, { params });
    return res.data;          // { status, user_id, extracted, verified }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── System Monitoring ────────────────────────────────────

/** GET /api/ocr/progress — aggregate job counts */
export async function apiGetProgress() {
  try {
    const res = await api.get('/ocr/progress');
    return res.data;          // { total, pending, processing, completed, failed, percent_complete }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/health/full — real Supabase check, used by SystemHealth page only */
export async function apiGetHealth() {
  try {
    const res = await api.get('/health/full', { timeout: 20000 });
    return res.data;          // { status, supabase, workers, env_loaded, queue_depth }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/signed-url?storage_path=... */
export async function apiGetSignedUrl(storagePath, expiresIn = 3600) {
  try {
    const res = await api.get('/signed-url', {
      params: { storage_path: storagePath, expires_in: expiresIn },
    });
    return res.data;          // { status, signed_url }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Intelligence Layer ────────────────────────────────────────

/**
 * POST /api/evaluate/:userId
 * Runs score → decide → suggest → persist pipeline.
 * @param {number} userId
 * @param {boolean} force  re-evaluate even if already done
 */
export async function apiEvaluateUser(userId, force = false) {
  try {
    const res = await api.post(`/evaluate/${userId}`, null, { params: { force } });
    return res.data;
    // { status, user_id, evaluations: [...], summary: { total_docs, approved, review, rejected } }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/evaluate/summary
 * Returns aggregate decision counts from verified_data.
 */
export async function apiGetEvaluateSummary() {
  try {
    const res = await api.get('/evaluate/summary');
    return res.data;   // { status, total, approved, review, rejected, pending }
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/analytics/dashboard
 * Single authoritative source for all Dashboard metrics.
 * Derived from real Supabase rows — no heuristics.
 */
export async function apiGetDashboard(period = 'week', trendDays = 14) {
  try {
    const res = await api.get('/analytics/dashboard', {
      params: { period, trend_days: trendDays, _t: Date.now() },
    });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

export async function apiAnalyzeAcademic(file, docType = 'auto') {
  try {
    const fd = new FormData();
    fd.append('file', file);
    if (docType && docType !== 'auto') {
      fd.append('doc_type', docType);
    }
    const res = await api.post('/academic/analyze', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Academic Engine v2 ───────────────────────────────────────────

/**
 * POST /api/v2/academic/analyze
 * New isolated academic engine — full pipeline with auto-classification.
 */
export async function apiAnalyzeAcademicV2(file, docType = 'auto') {
  try {
    const fd = new FormData();
    fd.append('file', file);
    if (docType && docType !== 'auto') {
      fd.append('doc_type', docType);
    }
    const res = await api.post('/v2/academic/analyze', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000,   // 120s — PDF light pipeline targets 5–15s, but allow headroom
    });
    return res.data;
  } catch (err) {
    // Distinguish timeout from true network failure so the Navbar stays Online
    if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
      throw new Error('Extraction timed out (>120s). The document may be too complex — try a smaller file.');
    }
    const detail = err?.response?.data?.detail;
    if (detail && typeof detail === 'object') {
      const msg = detail.errors?.join(', ') || detail.message || JSON.stringify(detail);
      throw new Error(msg);
    }
    throw new Error(apiErr(err));
  }
}

/**
 * POST /api/v2/academic/analyze/bulk
 * Bulk upload — multiple documents concurrently.
 */
export async function apiAnalyzeAcademicBulk(files, docType = 'auto') {
  try {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    if (docType && docType !== 'auto') fd.append('doc_type', docType);
    const res = await api.post('/v2/academic/analyze/bulk', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300000,   // 5 minutes for bulk
    });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/v2/academic/list/all */
export async function apiListAcademicAnalyses(limit = 20) {
  try {
    const res = await api.get('/v2/academic/list/all', { params: { limit } });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/v2/academic/{doc_id} */
export async function apiGetAcademicResult(docId) {
  try {
    const res = await api.get(`/v2/academic/${docId}`);
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Academic Document Scanner (Step 1) ──────────────────────────────────────

/**
 * POST /api/v2/scanner/restore
 * Run the full 10-stage document restoration pipeline on a raw image / PDF.
 *
 * Returns:
 *  {
 *    success:        boolean,
 *    original_b64:   string   (base64 JPEG),
 *    restored_b64:   string   (base64 JPEG),
 *    quality_report: { quality_score, blur_score, brightness_score, ... },
 *    stage_metadata: { ... },
 *    debug_session:  string,
 *    elapsed_ms:     number,
 *  }
 */
export async function apiRestoreDocument(file, aggressive = false) {
  try {
    const fd = new FormData();
    fd.append('file', file);
    const res = await api.post('/v2/scanner/restore', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120_000,   // 2-minute timeout — SR + NLM can be slow
      params: { aggressive },
    });
    return res.data;
  } catch (err) {
    const detail = err?.response?.data?.detail;
    if (detail && typeof detail === 'object') {
      throw new Error(detail.message || JSON.stringify(detail));
    }
    throw new Error(apiErr(err));
  }
}

/** GET /api/v2/scanner/health */
export async function apiScannerHealth() {
  try {
    const res = await api.get('/v2/scanner/health');
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Robustness Testing ───────────────────────────────────────────────────────

/**
 * POST /api/v2/academic/robustness/run
 * Run adversarial benchmark on a clean reference document.
 *
 * @param {File}   file          Clean reference image
 * @param {Object} groundTruth   { percentage, candidate_name, cgpa, result, ... }
 * @param {Object} opts          { transforms, maxVariants, maxWorkers, seed }
 */
export async function apiRunRobustness(file, groundTruth = {}, opts = {}) {
  try {
    const fd = new FormData();
    fd.append('file', file);
    if (Object.keys(groundTruth).length > 0) {
      fd.append('ground_truth', JSON.stringify(groundTruth));
    }
    if (opts.transforms?.length) {
      fd.append('transforms', JSON.stringify(opts.transforms));
    }
    fd.append('max_variants', String(opts.maxVariants ?? 40));
    fd.append('max_workers',  String(opts.maxWorkers  ?? 2));
    fd.append('seed',         String(opts.seed        ?? 42));
    const res = await api.post('/v2/academic/robustness/run', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 600_000,   // 10 minutes for bulk testing
    });
    return res.data;
  } catch (err) {
    const detail = err?.response?.data?.detail;
    throw new Error(typeof detail === 'string' ? detail : apiErr(err));
  }
}

/** GET /api/v2/academic/robustness/report/:id */
export async function apiGetRobustnessReport(reportId) {
  try {
    const res = await api.get(`/v2/academic/robustness/report/${reportId}`);
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/** GET /api/v2/academic/robustness/transforms */
export async function apiListRobustnessTransforms() {
  try {
    const res = await api.get('/v2/academic/robustness/transforms');
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

// ─── Academic Storage Diagnostic ──────────────────────────────────────────────

/**
 * GET /api/debug/academic-storage[?user_id=N]
 *
 * Runs a full DB diagnostic:
 *   1. Counts rows per academic doc_type in the documents table
 *   2. Lists recent academic rows
 *   3. Runs a probe INSERT+DELETE to test the CHECK constraint
 *   4. Returns a plain-English "diagnosis" field
 *
 * Usage (browser console):
 *   import('/api/api.js').then(m => m.apiDebugAcademicStorage().then(console.log))
 *
 * Or just hit:  http://127.0.0.1:8000/api/debug/academic-storage
 */
export async function apiDebugAcademicStorage(userId = null) {
  try {
    const params = userId ? { user_id: userId } : {};
    const res = await api.get('/debug/academic-storage', { params });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}

/**
 * GET /api/users/{userId}/academic-records
 * Fetch all academic OCR extraction records linked to a candidate_id.
 * These come from extracted_data with doc_type in [tenth, twelfth, diploma, degree, semester].
 *
 * Returns: {
 *   success: boolean,
 *   candidate_id: number,
 *   count: number,
 *   academic_records: [{
 *     id, candidate_id, document_type,
 *     extracted_percentage, extracted_grade, extracted_name, extracted_year,
 *     ocr_confidence, file_path, created_at
 *   }]
 * }
 */
export async function apiGetAcademicRecords(userId) {
  try {
    const res = await api.get(`/users/${userId}/academic-records`, { timeout: 10_000 });
    return res.data;
  } catch (err) {
    throw new Error(apiErr(err));
  }
}
