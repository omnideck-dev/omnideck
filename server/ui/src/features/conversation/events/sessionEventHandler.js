import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isRootAgentEvent,
} from './eventTypes.js';

// Records retained by the open frontend session so it can build Turns. This
// is a UI policy, not the backend's separate durability policy.
const RETAINED_SESSION_EVENT_TYPES = new Set([
    EVENT.AGENT_STARTED,
    EVENT.AGENT_COMPLETED,
    EVENT.USER_MESSAGE,
    EVENT.ITERATION,
    EVENT.TOOL_RESULT,
    EVENT.COMPACTION,
    EVENT.FILE_OUTPUT,
    EVENT.SPAWN_REQUESTED,
    EVENT.ERROR,
]);

/** Apply a canonical event to state owned by the open conversation session. */
export function handleSessionEvent(event, actions = {}) {
    if (!event?.type) return;

    if (RETAINED_SESSION_EVENT_TYPES.has(event.type)) {
        actions.retainEvent?.(event);
    }

    switch (event.type) {
        case EVENT.USER_MESSAGE:
            actions.confirmUserMessage?.();
            break;
        case EVENT.ITERATION:
            actions.finalizeIteration?.();
            break;
        case EVENT.CONTENT:
            if (event.agent_id) actions.updateInProgressIteration?.(event);
            break;
        case EVENT.AGENT_STARTED:
            if (event.agent_id && isRootAgentEvent(event)) actions.setRootAgent?.(event);
            break;
        case EVENT.TURN_END:
            actions.finishTurn?.();
            break;
        default:
            break;
    }
}
