import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isRootAgentEvent,
} from './eventTypes.js';

// Records retained by the open frontend session so it can build Turns. This
// is a UI policy, not the backend's separate durability policy.
/** @type {Set<import('./conversationEvents.generated').ConversationEvent['type']>} */
const RETAINED_SESSION_EVENT_TYPES = new Set([
    EVENT.AGENT_STARTED,
    // Marks the turn finished, so goal run outcomes can show.
    EVENT.AGENT_COMPLETED,
    EVENT.USER_MESSAGE,
    EVENT.ITERATION,
    EVENT.TOOL_RESULT,
    EVENT.COMPACTION,
    EVENT.FILE_OUTPUT,
    EVENT.SPAWN_REQUESTED,
    EVENT.ERROR,
]);

/**
 * Convert a canonical event into open-session reducer actions.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {Array<import('./frontendTypes').SessionAction>}
 */
export function getSessionEventActions(event) {
    /** @type {Array<import('./frontendTypes').SessionAction>} */
    const actions = [];
    if (!event?.type) return actions;
    const isRootEvent = isRootAgentEvent(event);

    if (isRootEvent && (RETAINED_SESSION_EVENT_TYPES.has(event.type)
        || (event.type === EVENT.GOAL && event.data.kind !== 'state_notice'))) {
        actions.push({ type: 'RETAIN_EVENT', event });
    }

    switch (event.type) {
        case EVENT.USER_MESSAGE:
            if (isRootEvent) actions.push({ type: 'CONFIRM_USER_MESSAGE' });
            // A queued message leaves the queue once the agent reads it.
            if (event.nudge_id) {
                actions.push({ type: 'DROP_QUEUED_MESSAGE', nudgeId: event.nudge_id, returned: false });
            }
            break;
        // Queue events are replayed with the run but never saved in the chat.
        case EVENT.NUDGE_QUEUED:
            actions.push({
                type: 'QUEUE_MESSAGE',
                message: {
                    id: event.nudge_id,
                    content: event.content || '',
                    context: Array.isArray(event.context) ? event.context : [],
                },
            });
            break;
        case EVENT.NUDGE_REMOVED:
            actions.push({ type: 'DROP_QUEUED_MESSAGE', nudgeId: event.nudge_id, returned: event.reason === 'returned' });
            break;
        case EVENT.ITERATION:
            if (isRootEvent) actions.push({ type: 'FINALIZE_ITERATION' });
            break;
        case EVENT.CONTENT:
            if (isRootEvent && event.agent_id) {
                actions.push({ type: 'UPDATE_IN_PROGRESS_ITERATION', event });
            }
            break;
        case EVENT.AGENT_STARTED:
            if (event.agent_id && isRootAgentEvent(event)) {
                actions.push({ type: 'SET_ROOT_AGENT', agentId: event.agent_id });
            }
            break;
        case EVENT.TURN_END:
            actions.push({ type: 'FINISH_TURN' });
            break;
        default:
            break;
    }
    return actions;
}
