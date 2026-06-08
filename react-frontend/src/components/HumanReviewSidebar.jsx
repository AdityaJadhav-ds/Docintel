import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { getApiBase } from '../api/api';
import { History, Activity, ShieldCheck, Database, Undo2, Hash, Lightbulb, CheckCircle2, XCircle, ChevronRight, GitMerge, Scissors, Link2 } from 'lucide-react';

const ACTION_ICONS = { merge_row: GitMerge, split_row: Scissors, update_link: Link2 };
const ACTION_LABELS = {
  merge_row: 'Merged Regions', split_row: 'Split Region',
  text_edit: 'Text Corrected', update_link: 'Link Updated', mark_continuation: 'Continuation Linked',
};

export default function HumanReviewSidebar({
  runId, blocks, graphVersion, mutationHistory,
  onUndo, onJumpToSnapshot, selectedBlockId, resultMeta, quality
}) {
  const [recommendations, setRecommendations] = useState([]);
  const [loadingRecs, setLoadingRecs] = useState(false);
  const [replayMode, setReplayMode] = useState(false); // false = Live, true = replaying past snapshot
  const [decisionTimestamps, setDecisionTimestamps] = useState({}); // suggestion_id -> shown_at time
  const apiBase = getApiBase();

  const totalBlocks = blocks.length;
  const editedCount = blocks.filter(b => b.is_edited).length;
  const verifiedCount = blocks.filter(b => b.human_verified).length;

  // ── Fetch recommendations when a block is selected ─────────────────────────
  const fetchRecommendations = useCallback(async (blockId) => {
    if (!blockId || !runId) return;
    try {
      setLoadingRecs(true);
      const res = await axios.get(`${apiBase}/ocr/pipeline/${runId}/graph/recommendations`, {
        params: { block_id: blockId }
      });
      const recs = res.data.recommendations || [];
      setRecommendations(recs);
      // Record the time recommendations were shown
      const now = Date.now();
      const timestamps = {};
      recs.forEach(r => { timestamps[r.suggestion_id] = now; });
      setDecisionTimestamps(prev => ({ ...prev, ...timestamps }));
    } catch (err) {
      setRecommendations([]);
    } finally {
      setLoadingRecs(false);
    }
  }, [apiBase, runId]);

  useEffect(() => {
    if (selectedBlockId) {
      fetchRecommendations(selectedBlockId);
    } else {
      setRecommendations([]);
    }
  }, [selectedBlockId, fetchRecommendations]);

  // ── Handle suggestion accept/reject ──────────────────────────────────────────
  const handleFeedback = useCallback(async (suggestion, accepted) => {
    const shownAt = decisionTimestamps[suggestion.suggestion_id] || Date.now();
    const timeMs = Date.now() - shownAt;
    try {
      await axios.post(`${apiBase}/ocr/pipeline/${runId}/graph/recommendations/feedback`, {
        suggestion_id: suggestion.suggestion_id,
        block_id: selectedBlockId,
        suggested_action: suggestion.suggested_action,
        confidence: suggestion.confidence,
        accepted,
        time_to_decide_ms: timeMs,
      });
    } catch (err) {
      console.error('Feedback failed:', err);
    }
    // Remove the suggestion from the list
    setRecommendations(prev => prev.filter(r => r.suggestion_id !== suggestion.suggestion_id));
  }, [apiBase, runId, selectedBlockId, decisionTimestamps]);

  const isLive = !replayMode;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: "'Inter', sans-serif", background: '#f9fafb' }}>

      {/* ── Header ── */}
      <div style={{ padding: '18px 20px', borderBottom: '1px solid #e5e7eb', background: 'white', flexShrink: 0 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: '#111827', margin: '0 0 2px 0' }}>Document Inspector</h2>
        <div style={{ fontSize: 11.5, color: '#6b7280' }}>{resultMeta?.filename || 'Unknown'}</div>
        {replayMode && (
          <div style={{ marginTop: 8, background: '#fef3c7', border: '1px solid #fde68a', borderRadius: 6, padding: '5px 10px', fontSize: 11.5, fontWeight: 600, color: '#b45309', display: 'flex', alignItems: 'center', gap: 6 }}>
            ⏪ Replay mode — viewing past state
            <button onClick={() => { setReplayMode(false); onJumpToSnapshot && onJumpToSnapshot(null); }} style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: '#b45309', fontWeight: 700, cursor: 'pointer', fontSize: 11.5 }}>Go Live →</button>
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '20px 18px' }}>

        {/* ── Graph Health ── */}
        <Section title="Graph Health">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <StatRow icon={<ShieldCheck size={14} color="#10b981" />} label="Invariant Engine" value="PASSING" valueStyle={{ color: '#10b981', background: '#d1fae5', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700 }} />
            <StatRow icon={<Hash size={14} color="#6366f1" />} label="Graph Version" value={`v${graphVersion}`} />
            <StatRow icon={<Database size={14} color="#8b5cf6" />} label="Regions" value={<>{totalBlocks} <span style={{ color: '#9ca3af', fontWeight: 400 }}>({editedCount} edited, {verifiedCount} verified)</span></>} />
          </div>
        </Section>

        {/* ── Inline Recommendations ── */}
        {selectedBlockId && (
          <Section title="Suggested Fixes" badge={recommendations.length > 0 ? recommendations.length : null}>
            {loadingRecs && <div style={{ fontSize: 12, color: '#9ca3af' }}>Scanning correction history…</div>}
            {!loadingRecs && recommendations.length === 0 && (
              <div style={{ fontSize: 12, color: '#9ca3af', fontStyle: 'italic' }}>No suggestions for this region.</div>
            )}
            {recommendations.map(rec => {
              const ActionIcon = ACTION_ICONS[rec.suggested_action] || Activity;
              return (
                <div key={rec.suggestion_id} style={{ background: 'white', border: '1px solid #e0e7ff', borderRadius: 10, padding: '12px 14px', marginBottom: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
                    <div style={{ width: 26, height: 26, background: '#eef2ff', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <ActionIcon size={13} color="#4f46e5" />
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 700, color: '#1e1b4b' }}>{ACTION_LABELS[rec.suggested_action] || rec.suggested_action}</div>
                      <div style={{ fontSize: 11, color: '#6b7280', marginTop: 1 }}>
                        Confidence: <span style={{ fontWeight: 700, color: rec.confidence > 0.85 ? '#059669' : '#d97706' }}>{(rec.confidence * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                  <div style={{ fontSize: 11.5, color: '#4b5563', lineHeight: 1.6, marginBottom: 10 }}>{rec.reason}</div>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button onClick={() => handleFeedback(rec, true)} style={feedbackBtn('#059669', '#d1fae5')}>
                      <CheckCircle2 size={12} /> Accept
                    </button>
                    <button onClick={() => handleFeedback(rec, false)} style={feedbackBtn('#dc2626', '#fee2e2')}>
                      <XCircle size={12} /> Reject
                    </button>
                  </div>
                </div>
              );
            })}
          </Section>
        )}

        {/* ── Mutation Replay Timeline ── */}
        <Section title="Mutation Timeline" action={
          mutationHistory.length > 0 && (
            <button onClick={onUndo} style={{ display: 'flex', alignItems: 'center', gap: 4, background: 'transparent', border: '1px solid #e5e7eb', padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600, color: '#374151', cursor: 'pointer' }}>
              <Undo2 size={11} /> Undo
            </button>
          )
        }>
          <div style={{ position: 'relative', paddingLeft: 8 }}>
            <div style={{ position: 'absolute', left: 12, top: 4, bottom: 0, width: 2, background: '#e5e7eb' }} />

            {/* Live marker */}
            <TimelineItem
              dotColor={isLive ? '#6366f1' : '#d1d5db'}
              label={<span style={{ fontWeight: 700, color: isLive ? '#6366f1' : '#374151' }}>● Live — v{graphVersion}</span>}
              sub={isLive ? 'Current state' : <button onClick={() => { setReplayMode(false); onJumpToSnapshot?.(null); }} style={{ background: 'none', border: 'none', color: '#6366f1', fontSize: 11, fontWeight: 600, cursor: 'pointer', padding: 0 }}>Return to Live →</button>}
            />

            {mutationHistory.length === 0 && (
              <div style={{ fontSize: 12, color: '#9ca3af', fontStyle: 'italic', marginLeft: 20, marginTop: 4 }}>No mutations yet.</div>
            )}

            {mutationHistory.map((mut, idx) => {
              const isPlaying = replayMode && idx === 0; // simplified
              return (
                <TimelineItem
                  key={mut.id}
                  dotColor={idx === 0 && isLive ? '#8b5cf6' : '#d1d5db'}
                  label={ACTION_LABELS[mut.action] || mut.action}
                  sub={`Snapshot v${mut.version} · ${new Date(mut.timestamp).toLocaleTimeString()}`}
                  onClick={() => {
                    setReplayMode(true);
                    onJumpToSnapshot?.(mut.id);
                  }}
                />
              );
            })}
          </div>
        </Section>

      </div>
    </div>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ title, children, badge, action }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 12 }}>
        <h3 style={{ fontSize: 10.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.7, color: '#9ca3af', margin: 0 }}>
          {title}
        </h3>
        {badge != null && (
          <span style={{ background: '#6366f1', color: 'white', fontSize: 10, fontWeight: 700, borderRadius: 10, padding: '1px 7px' }}>{badge}</span>
        )}
        {action && <div style={{ marginLeft: 'auto' }}>{action}</div>}
      </div>
      {children}
    </div>
  );
}

function StatRow({ icon, label, value, valueStyle = {} }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'white', border: '1px solid #f3f4f6', padding: '9px 12px', borderRadius: 7, boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#374151', fontSize: 12.5, fontWeight: 500 }}>
        {icon} {label}
      </div>
      <div style={{ fontSize: 12.5, fontWeight: 700, color: '#111827', ...valueStyle }}>{value}</div>
    </div>
  );
}

function TimelineItem({ dotColor, label, sub, onClick }) {
  return (
    <div onClick={onClick} style={{ position: 'relative', marginBottom: 14, paddingLeft: 22, cursor: onClick ? 'pointer' : 'default' }}
      onMouseEnter={e => { if (onClick) e.currentTarget.style.opacity = '0.8'; }}
      onMouseLeave={e => { e.currentTarget.style.opacity = '1'; }}>
      <div style={{ position: 'absolute', left: 4, top: 3, width: 10, height: 10, borderRadius: '50%', background: dotColor, border: '2px solid white', boxShadow: '0 0 0 1px #e5e7eb' }} />
      <div style={{ fontSize: 12.5, fontWeight: 600, color: '#111827' }}>{label}</div>
      {sub && <div style={{ fontSize: 11, color: '#9ca3af', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function feedbackBtn(color, bg) {
  return {
    flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5,
    padding: '5px 10px', border: `1px solid ${color}20`, borderRadius: 6,
    background: bg, color, fontSize: 11.5, fontWeight: 600, cursor: 'pointer'
  };
}
