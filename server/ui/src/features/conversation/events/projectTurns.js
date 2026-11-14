import {
    CONVERSATION_EVENT_TYPES as EVENT,
    TRANSCRIPT_ITEM_KINDS as ITEM,
    isRootAgentEvent,
    isSubAgentEvent,
} from './eventTypes.js';
import { addDayHeaders, hideRunAfterStart, placeRunOutcomes } from './goalTranscript.js';

/** Display rules applied after the events become items, in this order. */
const TRANSCRIPT_PASSES = [placeCompactions, hideRunAfterStart, placeRunOutcomes, addDayHeaders];

/**
 * Build the chat transcript from the persisted conversation event log.
 *
 * “Transcript” means the chat-facing model: one Turn for each user interaction
 * with the root agent, containing ordered user prompts, assistant iterations,
 * files, spawn cards, compaction chips, errors, and supporting tool-result
 * records. Turn renders the visible items and deliberately leaves supporting
 * records to the activity UI. This is not the complete event history or the
 * per-agent activity log.
 *
 * For example:
 *
 *     events: [root agent_started, user_message, iteration]
 *        => [{ children: [user_prompt, iteration] }]
 *
 * A sub-agent's events are omitted here because its detailed output appears in
 * the agent network/activity view. The root transcript can still contain the
 * `spawn_requested` item that links to that sub-agent.
 *
 * The loop below only turns events into items, in the order they happened.
 * Display rules that move, hide or add items run afterwards as separate
 * passes, in the order listed in TRANSCRIPT_PASSES.
 *
 * @param {Array<import('./conversationEvents.generated').ConversationEvent>|null|undefined} events
 * @returns {Array<import('./frontendTypes').ConversationTurn>}
 */
export function projectTurns(events) {
    if (!Array.isArray(events)) return [];
    /** @type {Array<import('./frontendTypes').ConversationTurn>} */
    const turns = [];
    /** @type {import('./frontendTypes').ConversationTurn|null} */
    let currentTurn = null;

    for (const ev of events) {
        if (!ev) continue;
        const t = ev.type;

        if (t === EVENT.AGENT_STARTED) {
            if (isRootAgentEvent(ev)) {
                // A root agent starts once per user interaction, so it creates
                // a new top-level chat Turn.
                currentTurn = {
                    id: `turn_${turns.length}`,
                    agentId: ev.agent_id,
                    finished: false,
                    children: [],
                };
                turns.push(currentTurn);
            }
            // A sub-agent publishes the same agent_started event, but it has a
            // parent/depth and belongs to the agent graph inside the current
            // root turn. It must not create another top-level chat Turn.
            continue;
        }
        // Completion and context metadata affect the agent graph/status, not
        // the transcript's visible children. Completion of the root agent marks
        // the turn as finished.
        if (t === EVENT.AGENT_COMPLETED) {
            if (currentTurn && ev.agent_id === currentTurn.agentId) currentTurn.finished = true;
            continue;
        }
        if (t === EVENT.CONTEXT_USAGE) continue;
        // Every goal run that no user message started gets a divider, whatever
        // started it. Internal notes to the agent stay hidden.
        if (t === EVENT.GOAL) {
            const data = ev.data;
            if (data.kind === 'state_notice') continue;
            if (!currentTurn) {
                // No agent runs in this turn, so it has nothing left to finish.
                currentTurn = { id: `turn_${turns.length}`, agentId: null, finished: true, children: [] };
                turns.push(currentTurn);
            }
            const wakeup = data.kind === 'wakeup';
            currentTurn.children.push({
                kind: ITEM.GOAL_TRANSITION, id: ev.id,
                transition: wakeup ? 'run' : data.kind,
                objective: wakeup ? '' : data.objective,
                step: wakeup ? data.step : '',
                questionCount: wakeup ? 0 : data.question_count || 0,
                timestamp: ev.timestamp, resumeAt: wakeup ? null : data.resume_at,
            });
            continue;
        }

        if (!currentTurn) {
            // A root error with no turn yet means the turn failed before
            // the agent ever started (setup failure) — synthesize a turn
            // so the error still shows in the chat instead of being
            // dropped with the rest of the orphan events.
            if (t === EVENT.ERROR && isRootAgentEvent(ev)) {
                currentTurn = {
                    id: `turn_${turns.length}`,
                    agentId: ev.agent_id || null,
                    finished: true,
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
        // item in the conversation.
        if (isSubAgentEvent(ev)) continue;

        if (t === EVENT.USER_MESSAGE) {
            currentTurn.children.push({
                kind: ITEM.USER_PROMPT,
                id: ev.id,
                content: ev.content || '',
                attachments: ev.attachments || [],
                context: ev.context || [],
                isNudge: !!ev.is_nudge,
                timestamp: ev.timestamp || null,
            });
        } else if (t === EVENT.ITERATION) {
            currentTurn.children.push({
                kind: ITEM.ITERATION,
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
        } else if (t === EVENT.TOOL_RESULT) {
            currentTurn.children.push({
                kind: ITEM.TOOL_RESULT,
                id: ev.id,
                toolCallId: ev.tool_call_id,
                toolName: ev.tool_name,
                content: ev.content || '',
            });
        } else if (t === EVENT.FILE_OUTPUT) {
            currentTurn.children.push({
                kind: ITEM.FILE_OUTPUT,
                id: ev.id,
                filename: ev.filename,
                contentType: ev.content_type,
                path: ev.path || null,
                timestamp: ev.timestamp,
            });
        } else if (t === EVENT.COMPACTION) {
            currentTurn.children.push({
                kind: ITEM.COMPACTION,
                id: ev.id,
                summaryText: ev.summary_text || '',
                userIntentSummary: ev.user_intent_summary || '',
                stats: ev.stats || null,
                agentId: ev.agent_id || null,
                timestamp: ev.timestamp || null,
                keptFromId: ev.kept_from_id || null,
            });
        } else if (t === EVENT.SPAWN_REQUESTED) {
            currentTurn.children.push({
                kind: ITEM.SPAWN_REQUESTED,
                id: ev.id,
                correlationId: ev.correlation_id || null,
            });
        } else if (t === EVENT.ERROR) {
            currentTurn.children.push({
                kind: ITEM.ERROR,
                id: ev.id,
                message: ev.message || 'An error occurred.',
            });
        }
    }

    return TRANSCRIPT_PASSES.reduce((list, pass) => pass(list), turns);
}

/**
 * Keep the source event log in chronological order. Only rearrange these
 * derived transcript children so a compaction chip marks the semantic
 * boundary between summarized context and the iterations kept verbatim.
 * The backend emits the compaction after doing the work, while keptFromId
 * identifies the first iteration on the kept side of the boundary:
 *
 *     event order:      iter-1, iter-2, compaction(keptFromId=iter-2)
 *     transcript order: iter-1, [compaction], iter-2
 *                               summarized | kept verbatim
 *
 * @param {Array<import('./frontendTypes').ConversationTurn>} turns
 * @returns {Array<import('./frontendTypes').ConversationTurn>}
 */
export function placeCompactions(turns) {
    return turns.map((turn) => {
        const children = [...turn.children];
        const compactions = children.filter((c) => c.kind === ITEM.COMPACTION);
        for (const comp of compactions) {
            if (!comp.keptFromId) continue;
            const targetIdx = children.findIndex(
                (c) => c.kind === ITEM.ITERATION && c.id === comp.keptFromId,
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
        return { ...turn, children };
    });
}
