import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { getApiBase } from '../api/api';
import TableCorrectionCanvas from '../components/TableCorrectionCanvas';
import HumanReviewSidebar from '../components/HumanReviewSidebar';

export default function HumanReviewWorkspace({ runId }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Authoritative Graph State
  const [blocks, setBlocks] = useState([]);
  const [layoutMeta, setLayoutMeta] = useState({});
  const [graphVersion, setGraphVersion] = useState(0);
  const [mutationHistory, setMutationHistory] = useState([]);
  const [selectedBlockId, setSelectedBlockId] = useState(null);
  const [replaySnapshotId, setReplaySnapshotId] = useState(null);
  
  const apiBase = getApiBase();
  
  // Fetch initial state
  const loadResult = useCallback(async () => {
    try {
      setLoading(true);
      const res = await axios.get(`${apiBase}/ocr/pipeline/result/${runId}`);
      if (res.data && res.data.ready) {
        setResult(res.data);
        setBlocks(res.data.blocks || []);
        setLayoutMeta(res.data.layout_graph || {});
        // If the backend doesn't supply a version initially, assume 0
        setGraphVersion(res.data.graph_version || 0); 
      } else {
        setError('Result not ready or not found.');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [apiBase, runId]);

  useEffect(() => {
    loadResult();
  }, [loadResult]);

  // Dispatch mutation with expected_version lock
  const mutateGraph = useCallback(async (actionType, payload) => {
    // 1. Optimistic Local Update (predictive mutation layer)
    const backupBlocks = [...blocks];
    const backupMeta = { ...layoutMeta };
    
    // Minimal optimistic visual update (mark affected nodes as pending)
    if (payload.source_id && payload.target_id && actionType === 'merge_row') {
       setBlocks(prev => prev.map(b => {
           if (b.id === payload.source_id || b.id === payload.target_id) {
               return { ...b, _status: 'pending' };
           }
           return b;
       }));
    }

    try {
      const requestPayload = {
        ...payload,
        action_type: actionType,
        expected_version: graphVersion
      };
      
      const res = await axios.post(`${apiBase}/ocr/pipeline/${runId}/graph/mutate`, requestPayload);
      const data = res.data;
      
      // 2. Validate backend authoritative response
      if (data.status === 'accepted') {
        setGraphVersion(data.graph_version);
        setMutationHistory(prev => [{ id: data.mutation_id, action: actionType, version: data.graph_version, timestamp: Date.now() }, ...prev]);
        
        // 3. Apply exact deltas from backend (changed_nodes, deleted_links, new_links)
        // For simplicity, we merge the changed nodes into our block list
        const changedDict = {};
        (data.changed_nodes || []).forEach(n => {
           changedDict[n.id || n.node_id] = n;
        });
        
        setBlocks(prev => {
            const nextBlocks = prev.map(b => changedDict[b.id] ? changedDict[b.id] : b);
            // Append any entirely new nodes
            (data.changed_nodes || []).forEach(n => {
               if (!prev.find(pb => pb.id === (n.id || n.node_id))) {
                   nextBlocks.push(n);
               }
            });
            // Filter deleted
            return nextBlocks.filter(b => !b._deleted);
        });
        
      } else {
        // Rejected by invariant engine
        console.warn('Mutation rejected:', data.message);
        setBlocks(backupBlocks);
      }
      
    } catch (err) {
      // 4. Handle Stale Mutation (409 Conflict)
      if (err.response && err.response.status === 409) {
         console.warn('Stale mutation detected. Resyncing graph...');
         // Reload authoritative state from server
         loadResult();
      } else {
         console.error('Mutation failed:', err);
         setBlocks(backupBlocks); // Rollback optimistic UI
      }
    }
  }, [blocks, layoutMeta, graphVersion, apiBase, runId, loadResult]);

  const undoLastMutation = useCallback(async () => {
    try {
      const res = await axios.post(`${apiBase}/ocr/pipeline/${runId}/graph/undo`);
      if (res.data.status === 'restored') {
         // Reload full state since undo doesn't currently return deltas
         loadResult();
         setMutationHistory(prev => prev.slice(1));
      }
    } catch (err) {
      console.error('Undo failed:', err);
    }
  }, [apiBase, runId, loadResult]);

  if (loading) return <div style={{ padding: 40, fontFamily: 'Inter' }}>Loading Human Review Workspace...</div>;
  if (error) return <div style={{ padding: 40, color: 'red' }}>Error: {error}</div>;
  if (!result) return null;

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: 'Inter, sans-serif' }}>
      
      {/* Left Sidebar (Human Review Sidebar / Timeline) */}
      <div style={{ width: 340, flexShrink: 0, borderRight: '1px solid #e5e7eb', background: '#f9fafb' }}>
         <HumanReviewSidebar 
            runId={runId}
            blocks={blocks}
            graphVersion={graphVersion}
            mutationHistory={mutationHistory}
            onUndo={undoLastMutation}
            onJumpToSnapshot={setReplaySnapshotId}
            selectedBlockId={selectedBlockId}
            resultMeta={result.meta}
            quality={result.quality}
         />
      </div>

      {/* Main Workspace (Table Correction Canvas / Visual Debugger) */}
      <div style={{ flex: 1, overflow: 'auto', background: '#f0f4ff', position: 'relative' }}>
         <TableCorrectionCanvas 
            blocks={blocks}
            layoutMeta={layoutMeta}
            pageImages={result.images?.pages || []}
            pageDims={result.page_dims}
            onMutate={mutateGraph}
            onSelectBlock={setSelectedBlockId}
            selectedBlockId={selectedBlockId}
         />
      </div>
      
    </div>
  );
}
