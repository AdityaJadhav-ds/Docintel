import { useState } from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutGrid, UploadCloud, Sparkles,
  Database as DBIcon, FileText, Settings,
  Activity, Shield, Bug, GraduationCap, FlaskConical
} from 'lucide-react';

const NAV = [
  { to: '/dashboard', label: 'Dashboard',   icon: LayoutGrid  },
  { to: '/upload',    label: 'Upload',       icon: UploadCloud },
  { to: '/insights',  label: 'Intelligence', icon: Sparkles    },
  { to: '/database',  label: 'Database',     icon: DBIcon      },
  { to: '/audit',     label: 'Audit Logs',   icon: FileText    },
];

function NavItem({ icon: Icon, label, isActive }) {
  const [hov, setHov] = useState(false);
  const bg   = isActive ? '#DBEAFE' : hov ? '#F1F5F9' : 'transparent';
  const clr  = isActive ? '#1D4ED8' : hov ? '#0F172A' : '#334155';
  const iclr = isActive || hov ? '#2563EB' : '#64748B';
  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        height: 44, padding: '0 12px', borderRadius: 10,
        cursor: 'pointer', background: bg,
        transition: 'background 150ms ease', userSelect: 'none',
      }}
    >
      <Icon size={20} color={iclr} strokeWidth={isActive ? 2.5 : 2} style={{ flexShrink: 0, transition: 'color 150ms ease' }} />
      <span style={{ fontSize: 14, fontWeight: isActive ? 600 : 500, color: clr, flex: 1, letterSpacing: '-0.005em', transition: 'color 150ms ease' }}>
        {label}
      </span>
      {isActive && <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#2563EB', flexShrink: 0 }} />}
    </div>
  );
}

function ProfileRow() {
  const [hov, setHov] = useState(false);
  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 12px', borderRadius: 10,
        background: hov ? '#F8FAFC' : 'transparent',
        cursor: 'pointer', transition: 'background 150ms ease',
      }}
    >
      <div style={{
        width: 36, height: 36, borderRadius: '50%',
        background: '#E2E8F0',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontWeight: 700, fontSize: 14, color: '#0F172A', flexShrink: 0,
      }}>A</div>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Admin</div>
        <div style={{ fontSize: 12, color: '#64748B', marginTop: 1 }}>Administrator</div>
      </div>
      <Settings size={15} color={hov ? '#64748B' : '#CBD5E1'} strokeWidth={2} style={{ flexShrink: 0, transition: 'color 150ms ease' }} />
    </div>
  );
}

export default function Sidebar() {
  return (
    <aside style={{
      /* Fixed — never moves, never overlaps content */
      position: 'fixed',
      top: 0,
      left: 0,
      width: 240,
      height: '100vh',

      /* Solid white — no blur, no transparency */
      background: '#FFFFFF',
      borderRight: '1px solid #E2E8F0',

      /* Stack below navbar if needed, but above nothing */
      zIndex: 100,

      /* Internal layout */
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>

      {/* ── Logo ── */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '20px 16px',
        borderBottom: '1px solid #F1F5F9',
        flexShrink: 0,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 10,
          background: '#DBEAFE',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          <Shield size={18} color="#2563EB" strokeWidth={2.5} />
        </div>
        <div>
          <div style={{ fontSize: 17, fontWeight: 700, color: '#0F172A', letterSpacing: '-0.025em', lineHeight: 1.15 }}>DocIntel</div>
          <div style={{ fontSize: 12, color: '#64748B', marginTop: 2 }}>KYC Platform</div>
        </div>
      </div>

      {/* ── Nav ── */}
      <nav style={{ flex: 1, padding: '16px 12px', display: 'flex', flexDirection: 'column', gap: 2, overflowY: 'auto' }}>

        <p style={{ fontSize: 11, fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '0 4px', marginBottom: 6, userSelect: 'none' }}>
          Navigation
        </p>

        {NAV.map(({ to, label, icon }) => (
          <NavLink key={to} to={to} style={{ textDecoration: 'none' }}>
            {({ isActive }) => <NavItem icon={icon} label={label} isActive={isActive} />}
          </NavLink>
        ))}

        <div style={{ height: 1, background: '#F1F5F9', margin: '10px 0' }} />

        <p style={{ fontSize: 11, fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.08em', padding: '0 4px', marginBottom: 6, userSelect: 'none' }}>
          System
        </p>
        <NavLink to="/health" style={{ textDecoration: 'none' }}>
          {({ isActive }) => <NavItem icon={Activity} label="System Health" isActive={isActive} />}
        </NavLink>
        <NavLink to="/ocr-debug" style={{ textDecoration: 'none' }}>
          {({ isActive }) => <NavItem icon={Bug} label="Extraction Studio" isActive={isActive} />}
        </NavLink>


      </nav>

      {/* ── User ── */}
      <div style={{ padding: '12px', borderTop: '1px solid #F1F5F9', flexShrink: 0 }}>
        <ProfileRow />
      </div>
    </aside>
  );
}
