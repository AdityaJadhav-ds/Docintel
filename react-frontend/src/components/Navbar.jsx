import { useState, useRef, useEffect } from 'react';
import { useApiStatus } from '../hooks/useApiStatus';
import { Bell, Search, CheckCircle2, XCircle, AlertTriangle, Info } from 'lucide-react';
import { useNotification } from '../context/NotificationContext';

const NOTIF_ICONS = {
  success: { icon: CheckCircle2, color: '#16A34A', bg: '#DCFCE7' },
  error:   { icon: XCircle,      color: '#DC2626', bg: '#FEE2E2' },
  warning: { icon: AlertTriangle,color: '#D97706', bg: '#FEF3C7' },
  info:    { icon: Info,         color: '#2563EB', bg: '#DBEAFE' },
};

export default function Navbar({ title, subtitle }) {
  const { status } = useApiStatus();
  const [focused, setFocused] = useState(false);
  const [val, setVal] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const ref = useRef(null);
  const dropdownRef = useRef(null);
  
  const { notifications, markAllRead, markRead } = useNotification();
  const unreadCount = notifications.filter(n => !n.read).length;

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setShowDropdown(false);
      }
    };
    if (showDropdown) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showDropdown]);

  const S = {
    online:     { dot:'online',  label:'Connected',  color:'#16A34A', bg:'#DCFCE7', border:'#86EFAC' },
    connecting: { dot:'warning', label:'Connecting', color:'#D97706', bg:'#FEF3C7', border:'#FCD34D' },
    offline:    { dot:'offline', label:'Offline',    color:'#DC2626', bg:'#FEE2E2', border:'#FCA5A5' },
  };
  const s = S[status] || S.offline;

  useEffect(() => {
    const h = e => { if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); ref.current?.focus(); } };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  return (
    <header style={{
      height: 64, padding: '0 28px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: '#FFFFFF', borderBottom: '1px solid #E2E8F0',
      boxShadow: '0 1px 4px rgba(15,23,42,0.06)',
      position: 'sticky', top: 0, zIndex: 50, gap: 20,
    }}>

      {/* Title */}
      <div style={{ flexShrink: 0 }}>
        <h1 style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A', letterSpacing: '-0.02em', margin: 0, lineHeight: 1.2 }}>{title}</h1>
        {subtitle && <p style={{ fontSize: '12px', color: '#94A3B8', marginTop: 2, fontWeight: 400 }}>{subtitle}</p>}
      </div>

      {/* Search */}
      <div style={{ flex: 1, maxWidth: 420, position: 'relative' }}>
        <Search size={16} style={{
          position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)',
          color: focused ? '#2563EB' : '#94A3B8', pointerEvents: 'none', transition: 'color 130ms',
        }} />
        <input
          ref={ref} value={val} onChange={e => setVal(e.target.value)}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          placeholder="Search users, records…"
          style={{
            width: '100%', height: 42,
            paddingLeft: 40, paddingRight: 52,
            background: focused ? '#FFFFFF' : '#F8FAFC',
            border: `1.5px solid ${focused ? '#2563EB' : '#E2E8F0'}`,
            borderRadius: '12px', fontSize: '14px', color: '#0F172A', outline: 'none',
            fontFamily: 'inherit', transition: 'all 130ms ease',
            boxShadow: focused ? '0 0 0 3px rgba(37,99,235,0.15)' : 'none',
          }}
        />
        <kbd style={{ position:'absolute',right:12,top:'50%',transform:'translateY(-50%)',opacity:focused?0:0.6,transition:'opacity 130ms' }}>⌘K</kbd>
      </div>

      {/* Right */}
      <div style={{ display:'flex',alignItems:'center',gap:10,flexShrink:0 }}>

        <div ref={dropdownRef} style={{ position: 'relative' }}>
          <button style={{
            width:38,height:38,borderRadius:10,border:'1px solid #E2E8F0',
            background: showDropdown ? '#F8FAFC' : '#FFFFFF',
            cursor:'pointer',display:'flex',alignItems:'center',justifyContent:'center',
            color: showDropdown ? '#0F172A' : '#94A3B8',position:'relative',transition:'all 130ms',
          }}
            onClick={() => setShowDropdown(!showDropdown)}
          >
            <Bell size={16} strokeWidth={2} />
            {unreadCount > 0 && (
              <span style={{position:'absolute',top:8,right:8,width:6,height:6,borderRadius:'50%',background:'#EF4444',border:'1.5px solid #fff'}} />
            )}
          </button>
          
          {showDropdown && (
            <div style={{
              position: 'absolute', top: '100%', right: 0, marginTop: 8,
              width: 360, maxHeight: 400, overflowY: 'auto',
              background: '#FFFFFF', borderRadius: 14, border: '1px solid #E2E8F0',
              boxShadow: '0 20px 40px rgba(0,0,0,0.1)', zIndex: 100, display: 'flex', flexDirection: 'column'
            }}>
              <div style={{ padding: '14px 16px', borderBottom: '1px solid #E2E8F0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#F8FAFC', borderTopLeftRadius: 14, borderTopRightRadius: 14, flexShrink: 0 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: '#0F172A' }}>Notifications</div>
                {unreadCount > 0 && (
                  <button onClick={markAllRead} style={{ fontSize: 12, fontWeight: 600, color: '#2563EB', background: 'none', border: 'none', cursor: 'pointer' }}>Mark all as read</button>
                )}
              </div>
              <div style={{ flex: 1, overflowY: 'auto' }}>
                {notifications.length === 0 ? (
                  <div style={{ padding: 32, textAlign: 'center', color: '#94A3B8', fontSize: 13 }}>No notifications yet</div>
                ) : (
                  notifications.map(n => {
                    const cfg = NOTIF_ICONS[n.type] || NOTIF_ICONS.info;
                    const Icon = cfg.icon;
                    return (
                      <div key={n.id} onClick={() => markRead(n.id)} style={{
                        padding: 12, borderBottom: '1px solid #F1F5F9', cursor: 'pointer',
                        background: n.read ? '#FFFFFF' : '#EFF6FF',
                        display: 'flex', gap: 12, alignItems: 'flex-start',
                        transition: 'background 150ms'
                      }}
                      onMouseEnter={e => e.currentTarget.style.background = n.read ? '#F8FAFC' : '#DBEAFE'}
                      onMouseLeave={e => e.currentTarget.style.background = n.read ? '#FFFFFF' : '#EFF6FF'}
                      >
                        <div style={{ width: 32, height: 32, borderRadius: '50%', background: cfg.bg, color: cfg.color, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                          <Icon size={16} strokeWidth={2.5} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 13, fontWeight: 600, color: '#0F172A', display: 'flex', justifyContent: 'space-between' }}>
                            {n.title}
                            {!n.read && <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#2563EB', marginTop: 4, flexShrink: 0 }} />}
                          </div>
                          <div style={{ fontSize: 12, color: '#475569', marginTop: 2, lineHeight: 1.4 }}>{n.message}</div>
                          <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4, fontWeight: 500 }}>
                            {new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </div>

        <div style={{width:1,height:22,background:'#E2E8F0'}} />

        <div style={{
          display:'flex',alignItems:'center',gap:7,padding:'5px 14px',borderRadius:20,
          background:s.bg,border:`1px solid ${s.border}`,
          fontSize:'12.5px',fontWeight:700,color:s.color,userSelect:'none',
        }}>
          <span className={`status-dot ${s.dot}`} />
          {s.label}
        </div>

        <div style={{width:1,height:22,background:'#E2E8F0'}} />

        <div style={{
          width:36,height:36,borderRadius:'50%',
          background:'linear-gradient(135deg,#2563EB,#7C3AED)',
          color:'#fff',display:'flex',alignItems:'center',justifyContent:'center',
          fontWeight:800,fontSize:'13px',cursor:'pointer',
          boxShadow:'0 2px 8px rgba(37,99,235,0.3)',
        }} title="Admin">A</div>
      </div>
    </header>
  );
}
