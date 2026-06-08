/* eslint-disable react-refresh/only-export-components */
import React, { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-react';
import './Notification.css';

const NotificationContext = createContext(null);

const TYPE_CONFIG = {
  success: { icon: CheckCircle2, color: '#16A34A', bg: '#DCFCE7' },
  error:   { icon: XCircle,      color: '#DC2626', bg: '#FEE2E2' },
  warning: { icon: AlertTriangle,color: '#D97706', bg: '#FEF3C7' },
  info:    { icon: Info,         color: '#2563EB', bg: '#DBEAFE' },
};

export function NotificationProvider({ children }) {
  const [notifications, setNotifications] = useState([]);
  const [toasts, setToasts] = useState([]);

  const dismissToast = useCallback((id) => {
    setToasts(prev => prev.map(t => t.id === id ? { ...t, exiting: true } : t));
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 200); // Wait for exit animation
  }, []);

  const notify = useCallback((title, message, type = 'info') => {
    const id = Date.now() + Math.random().toString(36).substr(2, 9);
    const newNotif = { id, title, message, type, timestamp: new Date(), read: false };
    
    setNotifications(prev => [newNotif, ...prev]);
    setToasts(prev => [...prev, { ...newNotif, exiting: false }]);
    
    setTimeout(() => {
      dismissToast(id);
    }, 4000);
  }, [dismissToast]);

  const toast = useCallback((msg, type = 'success') => {
    let title = 'Notification';
    if (type === 'success') title = 'Success';
    if (type === 'error') title = 'Error';
    if (type === 'warning') title = 'Warning';
    if (type === 'info') title = 'Info';
    notify(title, msg, type);
  }, [notify]);

  const markAllRead = useCallback(() => {
    setNotifications(prev => prev.map(n => ({ ...n, read: true })));
  }, []);

  const markRead = useCallback((id) => {
    setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n));
  }, []);

  return (
    <NotificationContext.Provider value={{ notifications, notify, toast, markAllRead, markRead }}>
      {children}
      <div className="toast-container">
        {toasts.map(t => {
          const cfg = TYPE_CONFIG[t.type] || TYPE_CONFIG.info;
          const Icon = cfg.icon;
          return (
            <div 
              key={t.id} 
              className={`toast-item toast-${t.type} ${t.exiting ? 'toast-exit' : 'toast-enter'}`}
            >
              <div className="toast-icon-wrapper" style={{ color: cfg.color }}>
                <Icon size={20} strokeWidth={2.5} />
              </div>
              <div className="toast-content">
                <div className="toast-title">{t.title}</div>
                <div className="toast-desc">{t.message}</div>
              </div>
              <button className="toast-close" onClick={() => dismissToast(t.id)}>
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </NotificationContext.Provider>
  );
}

export const useNotification = () => useContext(NotificationContext);
// Backward compatibility wrapper
export const useToast = () => useContext(NotificationContext).toast;
