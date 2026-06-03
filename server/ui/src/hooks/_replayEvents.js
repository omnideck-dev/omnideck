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
 *   terminal_output    → UPDATE_TERMINAL
 *   browser_screenshot → UPDATE_BROWSER_SNAPSHOT
 *
 *   compaction         → APPEND_ACTIVITY {type: 'compaction', ...}
 *
 * Events without a matching live dispatch (user_message, tool_result,
 * context_usage) are skipped — chat-side state derives them directly
 * from the events array.
 */
export function replayEventsToAgentState(events, dispatch) {
    if (!Array.isArray(events) || !dispatch) return;
    for (const ev of events) {
        if (!ev || !ev.type) continue;
        const agentId = ev.agent_id;
        switch (ev.type) {
            case 'agent_started':
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
            case 'terminal_output':
                if (!agentId) break;
                dispatch({
                    type: 'UPDATE_TERMINAL',
                    agentId,
                    event: ev,
                });
                break;
            case 'browser_screenshot':
                if (!agentId) break;
                dispatch({
                    type: 'UPDATE_BROWSER_SNAPSHOT',
                    agentId,
                    snapshot: {
                        url: ev.url,
                        title: ev.title,
                        screenshot: ev.screenshot,
                        tabId: ev.tab_id ?? null,
                        agentId,
                    },
                });
                break;
            // user_message / tool_result / context_usage: not part of
            // useAgentState — chat derives them from events.
            default:
                break;
        }
    }
}
