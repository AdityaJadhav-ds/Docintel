import React, { useEffect, useState, useCallback, useRef } from 'react';
import { Doughnut, Line } from 'react-chartjs-2';
import {
  Chart as ChartJS, ArcElement, Tooltip, Legend,
  CategoryScale, LinearScale, PointElement, LineElement, Filler
} from 'chart.js';
import Navbar from '../components/Navbar';
import { apiGetDashboard } from '../api/api';
import {
  ShieldCheck, AlertTriangle, Activity, Zap,
  Users, Crosshair, BrainCircuit, Database,
  CheckCircle2, RefreshCw, TrendingUp, Clock,
  FileText, BarChart3, AlertCircle
} from 'lucide-react';

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale, LinearScale, PointElement, LineElement, Filler);

/* ── Animated Number ── */
function AnimatedNum({ value, decimals = 0, suffix = '' }) {
  const [n, setN] = useState(0);
  const raf = useRef(null);
  useEffect(() => {
    const target = parseFloat(value) || 0;
    const t0 = performance.now();
    const run = now => {
      const p = Math.min((now - t0) / 900, 1);
      const e = 1 - Math.pow(1 - p, 3);
      setN(target * e);
      if (p < 1) raf.current = requestAnimationFrame(run);
      else setN(target);
    };
    raf.current = requestAnimationFrame(run);
    return () => cancelAnimationFrame(raf.current);
  }, [value]);
  return <>{n.toFixed(decimals)}{suffix}</>;
}

/* ── Skeleton Block ── */
function Skeleton({ w = '100%', h = 16, r = 8, style = {} }) {
  return (
    <div style={{
      width: w, height: h, borderRadius: r,
      background: 'linear-gradient(90deg,#F1F5F9 25%,#E2E8F0 50%,#F1F5F9 75%)',
      backgroundSize: '600px 100%',
      animation: 'shimmer 1.4s ease-in-out infinite',
      ...style,
    }} />
  );
}

/* ── KPI Card ── */
function KpiCard({ title, value, decimals = 0, suffix = '', subtitle, icon: Icon, color, bg, badge, loading }) {
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 20 }}>
          <Skeleton w={40} h={40} r={12} />
          <Skeleton w={120} h={12} />
        </div>
        <Skeleton w={100} h={36} r={8} style={{ marginBottom: 12 }} />
        <Skeleton w={140} h={12} />
      </div>
    );
  }
  return (
    <div style={{ ...cardStyle, overflow: 'hidden', position: 'relative' }}>
      <div style={{ position: 'absolute', top: -20, right: -20, opacity: 0.06 }}>
        <Icon size={110} color={color} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
        <div style={{ width: 42, height: 42, borderRadius: 12, background: bg, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon size={20} color={color} />
        </div>
        <span style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{title}</span>
      </div>
      <div style={{ fontSize: 38, fontWeight: 800, color: '#0F172A', lineHeight: 1, marginBottom: 10, fontVariantNumeric: 'tabular-nums' }}>
        <AnimatedNum value={value} decimals={decimals} suffix={suffix} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {badge && (
          <span style={{ fontSize: 12, fontWeight: 700, color, background: bg, padding: '2px 10px', borderRadius: 20 }}>
            {badge}
          </span>
        )}
        <span style={{ fontSize: 13, color: '#94A3B8', fontWeight: 500 }}>{subtitle}</span>
      </div>
    </div>
  );
}

/* ── Stat Row ── */
function StatRow({ label, value, color = '#0F172A', bg = '#F8FAFC', loading }) {
  if (loading) return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 10, background: '#F8FAFC' }}>
      <Skeleton w={100} h={11} /><Skeleton w={40} h={11} />
    </div>
  );
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 14px', borderRadius: 10, background: bg }}>
      <span style={{ fontSize: 13.5, fontWeight: 600, color: '#475569', textTransform: 'capitalize' }}>
        {label.replace(/_/g, ' ')}
      </span>
      <span style={{ fontSize: 15, fontWeight: 800, color }}>{value}</span>
    </div>
  );
}

/* ── Anomaly Item ── */
function AnomalyItem({ anom }) {
  const isCrit = anom.severity === 'CRITICAL';
  return (
    <div style={{
      padding: '14px 16px', borderRadius: 12,
      background: isCrit ? '#FEF2F2' : '#FFFBEB',
      borderLeft: `3px solid ${isCrit ? '#EF4444' : '#F59E0B'}`,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: isCrit ? '#EF4444' : '#F59E0B', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          {isCrit ? 'Critical' : 'Warning'}
        </span>
      </div>
      <div style={{ fontSize: 13.5, fontWeight: 700, color: '#0F172A', marginBottom: 3, textTransform: 'capitalize' }}>
        {anom.anomaly_type?.replace(/_/g, ' ')}
      </div>
      <div style={{ fontSize: 12.5, color: '#475569', lineHeight: 1.5 }}>{anom.message}</div>
    </div>
  );
}

const cardStyle = {
  background: '#fff', borderRadius: 20, padding: 24,
  border: '1px solid #E2E8F0', boxShadow: '0 2px 8px rgba(15,23,42,0.04)',
  transition: 'box-shadow 0.2s, transform 0.2s',
};

const DONUT_COLORS = ['#10B981', '#F59E0B', '#EF4444', '#64748B', '#6366F1'];

/* ══════════════════════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════════════════════ */
export default function Dashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [period, setPeriod] = useState('week');
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);

  const loadData = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true);
    else if (!data) setLoading(true);
    try {
      const res = await apiGetDashboard(period, 14);
      setData(res);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [period]); // eslint-disable-line

  useEffect(() => {
    setData(null);
    setLoading(true);
    loadData();
  }, [period]); // eslint-disable-line


  /* Chart configs */
  const trendLabels = data?.trends?.daily?.map(d => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }) || [];
  const trendValues = data?.trends?.daily?.map(d => d.count) || [];

  const trendChart = {
    labels: trendLabels,
    datasets: [{
      label: 'Uploads',
      data: trendValues,
      borderColor: '#6366F1',
      backgroundColor: 'rgba(99,102,241,0.08)',
      borderWidth: 2.5,
      fill: true, tension: 0.4,
      pointRadius: 0, pointHoverRadius: 5,
    }]
  };
  const trendOpts = {
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      x: { display: true, grid: { display: false }, ticks: { font: { size: 10 }, color: '#94A3B8', maxTicksLimit: 5 } },
      y: { display: false, min: 0 },
    },
  };

  const validCounts = data?.validation ? {
    Verified: data.validation.verified || 0,
    Mismatch: data.validation.mismatch || 0,
    'Possible Mismatch': data.validation.possible_mismatch || 0,
    'OCR Failed': data.validation.ocr_failed || 0,
    Unknown: data.validation.unknown || 0
  } : {};
  const donutData = {
    labels: Object.keys(validCounts),
    datasets: [{ data: Object.values(validCounts), backgroundColor: DONUT_COLORS, borderWidth: 0, hoverOffset: 8 }]
  };
  const donutOpts = { responsive: true, maintainAspectRatio: false, cutout: '72%', plugins: { legend: { display: false } } };

  const isHealthy = data?.system_health === 'HEALTHY';
  const anomalyList = data?.anomalies?.anomalies || [];
  const anomalyTotal = data?.anomalies?.total || 0;

  /* ── Error State ── */
  if (error && !data) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#F8FAFC' }}>
        <Navbar title="Intelligence Center" subtitle="Enterprise Analytics Dashboard" />
        <div style={{ margin: 'auto', textAlign: 'center', padding: 48 }}>
          <div style={{ width: 72, height: 72, borderRadius: 20, background: '#FEE2E2', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 20px' }}>
            <AlertCircle size={36} color="#EF4444" />
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: '#0F172A', marginBottom: 8 }}>Dashboard Unavailable</h2>
          <p style={{ color: '#64748B', marginBottom: 24, maxWidth: 360, lineHeight: 1.6 }}>{error}</p>
          <button onClick={() => loadData(true)} className="btn btn-primary">
            <RefreshCw size={15} /> Retry Connection
          </button>
        </div>
      </div>
    );
  }

  const sk = loading; // skeleton mode

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#F8FAFC', minHeight: '100vh' }}>
      <Navbar title="Intelligence Center" subtitle="Real-time operational analytics" />

      <div style={{ padding: '32px 36px', maxWidth: 1600, margin: '0 auto', width: '100%' }}>

        {/* ── Page Header ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 28 }}>
          <div>
            <h1 style={{ fontSize: 26, fontWeight: 800, color: '#0F172A', margin: 0, letterSpacing: '-0.03em' }}>
              Analytics Dashboard
            </h1>
            <div style={{ fontSize: 13.5, color: '#64748B', marginTop: 5, display: 'flex', alignItems: 'center', gap: 10 }}>
              {sk ? <Skeleton w={200} h={12} /> : (
                <>
                  System:&nbsp;
                  <span style={{ fontWeight: 700, color: isHealthy ? '#10B981' : '#EF4444' }}>
                    {data?.system_health}
                  </span>
                  {lastUpdated && (
                    <>
                      <span style={{ width: 1, height: 12, background: '#E2E8F0', display: 'inline-block' }} />
                      <Clock size={12} color="#94A3B8" />
                      <span style={{ color: '#94A3B8' }}>Updated {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                    </>
                  )}
                </>
              )}
            </div>
          </div>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {/* Refresh button */}
            <button
              onClick={() => loadData(true)}
              disabled={refreshing || loading}
              style={{
                width: 38, height: 38, borderRadius: 10, border: '1px solid #E2E8F0',
                background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                cursor: 'pointer', color: '#64748B', transition: 'all 0.2s',
              }}
              title="Refresh"
            >
              <RefreshCw size={15} style={{ animation: refreshing ? 'spin 1s linear infinite' : 'none' }} />
            </button>

            {/* Period selector */}
            <div style={{ display: 'flex', background: '#fff', padding: 4, borderRadius: 12, border: '1px solid #E2E8F0', gap: 2 }}>
              {['today', 'week', 'month', 'all'].map(p => (
                <button key={p} onClick={() => setPeriod(p)} style={{
                  padding: '7px 16px', borderRadius: 8, border: 'none', fontSize: 12.5,
                  fontWeight: 600, textTransform: 'capitalize', cursor: 'pointer', transition: 'all 0.15s',
                  background: period === p ? '#0F172A' : 'transparent',
                  color: period === p ? '#fff' : '#64748B',
                }}>
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── KPI Cards Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20, marginBottom: 24 }}>
          <KpiCard loading={sk}
            title="OCR Accuracy" value={data?.ocr_success_rate} decimals={1} suffix="%"
            subtitle={sk ? '' : `Avg Conf: ${((data?.kpis?.avg_ocr_confidence || 0) * 100).toFixed(1)}%`}
            icon={Crosshair} color="#10B981" bg="#D1FAE5" badge="High Precision"
          />
          <KpiCard loading={sk}
            title="Fraud Detection" value={data?.fraud_rate} decimals={1} suffix="%"
            subtitle={sk ? '' : `${data?.high_risk_cases} critical cases flagged`}
            icon={ShieldCheck}
            color={data?.fraud_rate > 10 ? '#EF4444' : '#6366F1'}
            bg={data?.fraud_rate > 10 ? '#FEE2E2' : '#E0E7FF'}
          />
          <KpiCard loading={sk}
            title="Review Queue" value={data?.review_queue_size}
            subtitle="Pending manual review"
            icon={Users} color="#F59E0B" bg="#FEF3C7"
            badge={data?.review_queue_size > 100 ? 'Overloaded' : 'Healthy'}
          />
          <KpiCard loading={sk}
            title="Total Documents" value={data?.kpis?.total_documents}
            subtitle={sk ? '' : `${data?.kpis?.documents_today || 0} added today`}
            icon={FileText} color="#2563EB" bg="#EFF6FF"
          />
        </div>

        {/* ── Second KPI Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 20, marginBottom: 28 }}>
          {/* Trend Card */}
          <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Upload Trend</div>
                <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 2 }}>Last {data?.trend_days || 14} days</div>
              </div>
              <TrendingUp size={18} color="#6366F1" />
            </div>
            {sk ? <Skeleton w="100%" h={90} r={10} /> : (
              <div style={{ height: 90 }}>
                <Line data={trendChart} options={trendOpts} />
              </div>
            )}
          </div>

          {/* Auto-approved / rejected */}
          <div style={cardStyle}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 16 }}>
              Auto Decisions
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {sk ? (
                <>
                  <Skeleton w="100%" h={38} r={10} />
                  <Skeleton w="100%" h={38} r={10} />
                  <Skeleton w="100%" h={38} r={10} />
                </>
              ) : (
                <>
                  <StatRow label="Auto Approved" value={data?.kpis?.auto_approved ?? 0} color="#10B981" bg="#F0FDF4" />
                  <StatRow label="Auto Rejected" value={data?.kpis?.auto_rejected ?? 0} color="#EF4444" bg="#FEF2F2" />
                  <StatRow label="Duplicate Rate" value={`${((data?.kpis?.duplicate_rate || 0)).toFixed(1)}%`} color="#F59E0B" bg="#FFFBEB" />
                </>
              )}
            </div>
          </div>

          {/* Total Users */}
          <div style={{ ...cardStyle, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 16 }}>
              User Registry
            </div>
            {sk ? (
              <>
                <Skeleton w={80} h={48} r={8} style={{ marginBottom: 12 }} />
                <Skeleton w={160} h={12} />
              </>
            ) : (
              <>
                <div style={{ fontSize: 52, fontWeight: 800, color: '#0F172A', lineHeight: 1 }}>
                  <AnimatedNum value={data?.kpis?.total_users} />
                </div>
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 13, color: '#64748B', fontWeight: 500, marginBottom: 8 }}>Total registered users</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#2563EB', background: '#EFF6FF', padding: '3px 10px', borderRadius: 20 }}>
                      {data?.kpis?.documents_this_week || 0} docs this week
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* ── Bottom Row: Donut + Anomalies ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>

          {/* Processing Outcomes */}
          <div style={cardStyle}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 24 }}>
              <Database size={18} color="#6366F1" />
              <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0F172A', margin: 0 }}>Processing Outcomes</h3>
            </div>
            {sk ? (
              <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
                <Skeleton w={160} h={160} r="50%" style={{ flexShrink: 0 }} />
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <Skeleton w="100%" h={38} r={10} />
                  <Skeleton w="100%" h={38} r={10} />
                  <Skeleton w="100%" h={38} r={10} />
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: 28, alignItems: 'center' }}>
                <div style={{ width: 160, height: 160, flexShrink: 0 }}>
                  <Doughnut data={donutData} options={donutOpts} />
                </div>
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {Object.entries(validCounts).map(([key, val], i) => (
                    <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '9px 14px', borderRadius: 10, background: '#F8FAFC' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: '50%', background: DONUT_COLORS[i] || '#94A3B8', flexShrink: 0 }} />
                        <span style={{ fontSize: 13.5, fontWeight: 600, color: '#475569', textTransform: 'capitalize' }}>
                          {key.replace(/_/g, ' ')}
                        </span>
                      </div>
                      <span style={{ fontSize: 15, fontWeight: 800, color: '#0F172A' }}>{val}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* System Anomalies */}
          <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Activity size={18} color="#EF4444" />
                <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0F172A', margin: 0 }}>System Anomalies</h3>
              </div>
              {!sk && (
                <span style={{
                  background: anomalyTotal > 0 ? '#FEE2E2' : '#D1FAE5',
                  color: anomalyTotal > 0 ? '#EF4444' : '#10B981',
                  fontWeight: 700, padding: '4px 14px', borderRadius: 20, fontSize: 12.5,
                }}>
                  {anomalyTotal > 0 ? `${anomalyTotal} Detected` : 'All Clear'}
                </span>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 260, overflowY: 'auto' }}>
              {sk ? (
                <>
                  <Skeleton w="100%" h={72} r={12} />
                  <Skeleton w="100%" h={72} r={12} />
                </>
              ) : anomalyList.length > 0 ? (
                anomalyList.map((anom, idx) => <AnomalyItem key={idx} anom={anom} />)
              ) : (
                <div style={{ textAlign: 'center', padding: '40px 0', color: '#94A3B8' }}>
                  <CheckCircle2 size={36} style={{ marginBottom: 12, opacity: 0.5, display: 'block', margin: '0 auto 12px' }} />
                  <div style={{ fontSize: 14, fontWeight: 600, color: '#64748B' }}>No anomalies detected</div>
                  <div style={{ fontSize: 12.5, color: '#94A3B8', marginTop: 4 }}>System is operating normally</div>
                </div>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
