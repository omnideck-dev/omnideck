function _parseTimestamp(ts) {
    if (!ts) return Date.now();
    const ms = Date.parse(ts);
    return Number.isFinite(ms) ? ms : Date.now();
}

/**
 * Walk a persisted events.jsonl-shaped array and dispatch the same
 * actions a live SSE stream would, so the network view, per-agent
 * activity logs, and preview panels are restored on resume.
 *
 * Mapping mirrors the live SSE handler:
 *   agent_started      → AGENT_STARTED  (preserves real ids + parent links)
 *   agent_completed    → AGENT_COMPLETED
 *   iteration          → APPEND_STREAM_CHUNK (thinking + content) and
 *                        APPEND_ACTIVITY for each tool_call
 *   spawn_requested    → APPEND_ACTIVITY {type: 'spawn_requested'}
 *   file_output        → APPEND_ACTIVITY {type: 'file_output', ...}
 *   compaction         → APPEND_ACTIVITY {type: 'compaction', ...}
 *
 * Browser snapshots and terminal transcripts aren't in the event log —
 * they arrive via the resume payload's browser_tabs / terminal sidecars
 * and are dispatched by the caller.
 *
 * Events without a matching live dispatch (user_message, tool_result,
 * context_usage) are skipped — chat-side state derives them directly
 * from the events array.
 */
/**
 * Resolve the preview tabs to re-open on resume. open_files holds the saved
 * file PATHS (a file's full path is its identity — two files can share a
 * basename). Each path is matched to its file_output event to recover the
 * filename/content_type. Conversations saved before paths were stored hold
 * bare filenames, which won't match any path and simply don't restore.
 */
export function resolveOpenFiles(events, openPaths) {
    if (!Array.isArray(events) || !Array.isArray(openPaths)) return [];
    const byPath = new Map();
    for (const ev of events) {
        if (ev?.type === 'file_output' && ev.path) byPath.set(ev.path, ev);
    }
    const items = [];
    for (const p of openPaths) {
        const ev = byPath.get(p);
        if (ev) {
            items.push({
                type: 'file_output',
                filename: ev.filename,
                content_type: ev.content_type,
                path: ev.path,
                timestamp: ev.timestamp,
            });
        }
    }
    return items;
}

export function replayEventsToAgentState(events, dispatch) {
    if (!Array.isArray(events) || !dispatch) return;
    // Agents whose agent_completed never made it to the log (the app was
    // hard-killed mid-turn). Left as 'running' they'd show a perpetual
    // Thinking placeholder, so they're closed out as stopped after replay.
    const unfinished = new Map();
    for (const ev of events) {
        if (!ev || !ev.type) continue;
        const agentId = ev.agent_id;
        switch (ev.type) {
            case 'agent_started':
                unfinished.set(ev.agent_id, _parseTimestamp(ev.timestamp));
                dispatch({
                    type: 'AGENT_STARTED',
                    agentId: ev.agent_id,
                    agentName: ev.agent_name,
                    parentAgentId: ev.parent_agent_id || null,
                    instruction: ev.instruction || '',
                    correlationId: ev.correlation_id || null,
                    timestamp: _parseTimestamp(ev.timestamp),
                });
                break;
            case 'agent_completed':
                unfinished.delete(ev.agent_id);
                dispatch({
                    type: 'AGENT_COMPLETED',
                    agentId: ev.agent_id,
                    status: ev.status || 'success',
                    timestamp: _parseTimestamp(ev.timestamp),
                });
                break;
            case 'iteration': {
                if (!agentId) break;
                const thinking = ev.thinking || null;
                const content = ev.content || null;
                if (thinking || content) {
                    dispatch({
                        type: 'APPEND_STREAM_CHUNK',
                        agentId, content, thinking,
                    });
                }
                for (const tc of (ev.tool_calls || [])) {
                    dispatch({
                        type: 'APPEND_ACTIVITY',
                        agentId,
                        entry: {
                            type: 'tool_call',
                            name: tc.name,
                            arguments: tc.arguments || null,
                            timestamp: _parseTimestamp(ev.timestamp),
                        },
                    });
                }
                break;
            }
            case 'spawn_requested':
                if (!agentId) break;
                dispatch({
                    type: 'APPEND_ACTIVITY',
                    agentId,
                    entry: {
                        type: 'spawn_requested',
                        correlationId: ev.correlation_id || null,
                        timestamp: _parseTimestamp(ev.timestamp),
                    },
                });
                break;
            case 'file_output':
                if (!agentId) break;
                dispatch({
                    type: 'APPEND_ACTIVITY',
                    agentId,
                    entry: {
                        type: 'file_output',
                        filename: ev.filename,
                        content_type: ev.content_type,
                        path: ev.path || null,
                        timestamp: _parseTimestamp(ev.timestamp),
                    },
                });
                break;
            case 'compaction':
                if (!agentId) break;
                dispatch({
                    type: 'APPEND_ACTIVITY',
                    agentId,
                    entry: {
                        type: 'compaction',
                        stats: ev.stats || null,
                        summaryText: ev.summary_text || null,
                        userIntentSummary: ev.user_intent_summary || null,
                        timestamp: _parseTimestamp(ev.timestamp),
                    },
                });
                break;
            // user_message / tool_result / context_usage: not part of
            // useAgentState — chat derives them from events.
            default:
                break;
        }
        // Track the agent's latest activity so the synthetic completion
        // below freezes elapsed time at the last thing it actually did.
        if (agentId && unfinished.has(agentId)) {
            unfinished.set(agentId, _parseTimestamp(ev.timestamp));
        }
    }
    for (const [agentId, lastSeen] of unfinished) {
        dispatch({
            type: 'AGENT_COMPLETED',
            agentId,
            status: 'stopped',
            timestamp: lastSeen,
        });
    }
}
