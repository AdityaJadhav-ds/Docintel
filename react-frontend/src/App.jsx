import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { NotificationProvider } from './context/NotificationContext';
import { DataProvider } from './context/DataContext';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Upload   from './pages/Upload';
import Query    from './pages/Query';
import Database from './pages/Database';
import Audit    from './pages/Audit';
import SystemHealth from './pages/SystemHealth';
import ExtractionStudio from './pages/ExtractionStudio';
import RobustnessDashboard  from './pages/RobustnessDashboard';
import './App.css';

/* ── Layout ────────────────────────────────────────────
 *
 *  ┌──────────────┬───────────────────────────────────┐
 *  │   SIDEBAR    │          MAIN CONTENT             │
 *  │  (fixed)     │  margin-left:240px                │
 *  │  width:240px │  height:100vh  overflow-y:auto    │
 *  │  height:100vh│  Navbar (sticky top:0 inside here)│
 *  │  left:0      │  Page content below navbar        │
 *  └──────────────┴───────────────────────────────────┘
 *
 *  ALL layout values are INLINE — zero CSS class risk.
 * ─────────────────────────────────────────────────── */

const SIDEBAR_W = 240;

function Layout({ children }) {
  return (
    <div style={{
      display: 'flex',
      height: '100vh',
      width: '100vw',
      overflow: 'hidden',
      background: '#F8FAFC',
      position: 'relative',
    }}>
      {/* Fixed sidebar — 240px wide, never scrolls, never overlaps */}
      <Sidebar />

      {/* Main scroll container — starts AFTER the sidebar */}
      <main style={{
        marginLeft: SIDEBAR_W,
        width: `calc(100vw - ${SIDEBAR_W}px)`,
        height: '100vh',
        overflowY: 'auto',
        overflowX: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        background: '#F8FAFC',
        /* Sticky Navbar inside here pins to top of THIS scroll container */
      }}>
        {children}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <NotificationProvider>
      <DataProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/dashboard"       element={<Layout><Dashboard /></Layout>} />
            <Route path="/upload"          element={<Layout><Upload /></Layout>} />
            <Route path="/insights"        element={<Layout><Query /></Layout>} />
            <Route path="/decision-center" element={<Navigate to="/insights" replace />} />
            <Route path="/query"           element={<Navigate to="/insights" replace />} />
            <Route path="/database"        element={<Layout><Database /></Layout>} />
            <Route path="/audit"           element={<Layout><Audit /></Layout>} />
            <Route path="/health"          element={<Layout><SystemHealth /></Layout>} />
            <Route path="/ocr-debug"       element={<Layout><ExtractionStudio /></Layout>} />
            <Route path="/robustness"      element={<Layout><RobustnessDashboard /></Layout>} />
            <Route path="*"               element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
      </DataProvider>
    </NotificationProvider>
  );
}
