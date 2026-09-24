import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isSubAgentEvent,
} from './eventTypes.js';

/** @param {import('./conversationEvents.generated').ConversationEvent} event */
function eventTime(event) {
    const timestamp = Date.parse(event.timestamp);
    return Number.isFinite(timestamp) ? timestamp : Date.now();
}

/**
 * @param {string} agentId
 * @param {import('./frontendTypes').AgentActivityEntry} entry
 * @returns {import('./frontendTypes').AgentAction}
 */
function activityAction(agentId, entry) {
    return { type: 'APPEND_ACTIVITY', agentId, entry };
}

/**
 * Convert one canonical conversation event into agent reducer actions.
 *
 * Immediate actions update lifecycle and context metadata. Batched actions
 * enter the animation-frame queue to avoid rendering for every stream record.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {{immediate: Array<import('./frontendTypes').AgentAction>, batched: Array<import('./frontendTypes').AgentAction>}}
 */
export function getAgentEventActions(event) {
    /** @type {Array<import('./frontendTypes').AgentAction>} */
    const immediate = [];
    /** @type {Array<import('./frontendTypes').AgentAction>} */
    const batched = [];
    if (!event?.type) return { immediate, batched };

    const agentId = event.agent_id || null;
    if (!agentId) return { immediate, batched };
    const timestamp = eventTime(event);
    const retainActivity = isSubAgentEvent(event);

    switch (event.type) {
        case EVENT.AGENT_STARTED:
            immediate.push({
                type: 'AGENT_STARTED',
                agentId,
                agentName: event.agent_name,
                parentAgentId: event.parent_agent_id || null,
                instruction: event.instruction ?? null,
                correlationId: event.correlation_id || null,
                timestamp,
            });
            break;
        case EVENT.AGENT_COMPLETED:
            immediate.push({
                type: 'AGENT_COMPLETED',
                agentId,
                status: event.status,
                timestamp,
            });
            break;
        case EVENT.CONTEXT_USAGE:
            immediate.push({
                type: 'UPDATE_ITERATION',
                agentId,
                iteration: event.iteration ?? null,
                maxIterations: event.max_iterations ?? null,
                contextUsage: {
                    context_used: event.context_used,
                    context_limit: event.context_limit,
                    fill_ratio: event.fill_ratio,
                    compaction_threshold: event.compaction_threshold,
                },
            });
            break;
        case EVENT.CONTENT: {
            const content = event.content || '';
            const thinking = typeof event.thinking === 'string' ? event.thinking : '';
            if (retainActivity && (content || thinking)) {
                batched.push({
                    type: 'APPEND_STREAM_CHUNK',
                    agentId,
                    content: content || null,
                    thinking: thinking || null,
                });
            }
            break;
        }
        case EVENT.ITERATION:
            if (retainActivity) batched.push({
                type: 'FINALIZE_AGENT_ITERATION',
                agentId,
                content: event.content || null,
                thinking: event.thinking || null,
                toolCalls: event.tool_calls.map((toolCall) => ({
                    name: toolCall.name,
                    arguments: toolCall.arguments || null,
                })),
                timestamp,
            });
            break;
        case EVENT.SPAWN_REQUESTED:
            if (retainActivity) batched.push(activityAction(agentId, {
                type: 'spawn_requested',
                correlationId: event.correlation_id,
                timestamp,
            }));
            break;
        case EVENT.FILE_OUTPUT:
            if (retainActivity) batched.push(activityAction(agentId, {
                type: 'file_output',
                filename: event.filename,
                content_type: event.content_type,
                content: event.content ?? null,
                path: event.path ?? null,
                tool_call_id: event.tool_call_id ?? null,
                timestamp,
            }));
            break;
        case EVENT.COMPACTION:
            if (retainActivity) batched.push(activityAction(agentId, {
                type: 'compaction',
                stats: event.stats || null,
                summaryText: event.summary_text || null,
                userIntentSummary: event.user_intent_summary || null,
                timestamp,
            }));
            break;
        case EVENT.ERROR:
            if ((event.depth ?? 0) > 0) {
                batched.push(activityAction(agentId, {
                    type: 'error',
                    message: event.message || 'An error occurred.',
                    timestamp,
                }));
            }
            break;
        default:
            break;
    }

    return { immediate, batched };
}
