/**
 * Project the persisted conversation event log into chat turns.
 *
 * One Turn is created per root `agent_started` event. Each Turn contains an
 * ordered `children[]` collection of transcript items. Sub-agent events stay
 * out of this projection because they belong in the network and activity
 * views.
 */
export function projectTurns(events) {
    if (!Array.isArray(events)) return [];
    const turns = [];
    let currentTurn = null;

    for (const ev of events) {
        if (!ev) continue;
        const t = ev.type;

        if (t === 'agent_started' && !ev.parent_agent_id) {
            currentTurn = {
                id: `turn_${turns.length}`,
                agentId: ev.agent_id,
                children: [],
            };
            turns.push(currentTurn);
            continue;
        }
        // sub-agent lifecycle + non-chat metadata: ignore
        if (t === 'agent_started') continue;
        if (t === 'agent_completed') continue;
        if (t === 'context_usage') continue;

        if (!currentTurn) {
            // A root error with no turn yet means the turn failed before
            // the agent ever started (setup failure) — synthesize a turn
            // so the error still shows in the chat instead of being
            // dropped with the rest of the orphan events.
            if (t === 'error' && (ev.depth ?? 0) === 0) {
                currentTurn = {
                    id: `turn_${turns.length}`,
                    agentId: ev.agent_id || null,
                    children: [],
                };
                turns.push(currentTurn);
            } else {
                continue;
            }
        }

        // Everything from a sub-agent (depth>0) lives in the agent
        // activity view, not the main chat. Without this filter the
        // sub-agent's instruction user_message would render as a user
        // bubble in the conversation.
        if ((ev.depth ?? 0) > 0) continue;

        if (t === 'user_message') {
            currentTurn.children.push({
                kind: 'user_prompt',
                id: ev.id,
                content: ev.content || '',
                attachments: ev.attachments || [],
                isNudge: !!ev.is_nudge,
            });
        } else if (t === 'iteration') {
            currentTurn.children.push({
                kind: 'iteration',
                id: ev.id,
                iterationIndex: ev.iteration_index,
                content: ev.content || '',
                thinking: ev.thinking || '',
                toolCalls: (ev.tool_calls || []).map((tc) => ({
                    id: tc.id,
                    name: tc.name,
                    arguments: tc.arguments,
                })),
            });
        } else if (t === 'tool_result') {
            currentTurn.children.push({
                kind: 'tool_result',
                id: ev.id,
                toolCallId: ev.tool_call_id,
                toolName: ev.tool_name,
                content: ev.content || '',
            });
        } else if (t === 'file_output') {
            currentTurn.children.push({
                kind: 'file_output',
                id: ev.id,
                filename: ev.filename,
                contentType: ev.content_type,
                path: ev.path || null,
                timestamp: ev.timestamp,
            });
        } else if (t === 'compaction') {
            currentTurn.children.push({
                kind: 'compaction',
                id: ev.id,
                summaryText: ev.summary_text || '',
                userIntentSummary: ev.user_intent_summary || '',
                stats: ev.stats || null,
                agentId: ev.agent_id || null,
                timestamp: ev.timestamp || null,
                keptFromId: ev.kept_from_id || null,
            });
        } else if (t === 'spawn_requested') {
            currentTurn.children.push({
                kind: 'spawn_requested',
                id: ev.id,
                correlationId: ev.correlation_id || null,
            });
        } else if (t === 'error') {
            currentTurn.children.push({
                kind: 'error',
                id: ev.id,
                message: ev.message || 'An error occurred.',
            });
        }
    }

    // Reposition compactions: each chip belongs right before the
    // iteration whose id matches its keptFromId. The strategy emits the
    // compaction event AFTER the kept iteration in the log; the chip's
    // semantic place is BEFORE that iteration.
    for (const turn of turns) {
        const children = turn.children;
        const compactions = children.filter((c) => c.kind === 'compaction');
        for (const comp of compactions) {
            if (!comp.keptFromId) continue;
            const targetIdx = children.findIndex(
                (c) => c.kind === 'iteration' && c.id === comp.keptFromId,
            );
            if (targetIdx < 0) continue;
            const currentIdx = children.indexOf(comp);
            if (currentIdx < 0 || currentIdx === targetIdx - 1) continue;
            children.splice(currentIdx, 1);
            const newTargetIdx = currentIdx < targetIdx
                ? targetIdx - 1
                : targetIdx;
            children.splice(newTargetIdx, 0, comp);
        }
    }

    return turns;
}
