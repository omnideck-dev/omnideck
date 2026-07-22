import {
    CONVERSATION_EVENT_TYPES as EVENT,
    isRootAgentEvent,
} from './eventTypes.js';

// Records retained by the open frontend session so it can build Turns. This
// is a UI policy, not the backend's separate durability policy.
/** @type {Set<import('./conversationEvents.generated').ConversationEvent['type']>} */
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

/**
 * Apply a canonical event to state owned by the open conversation session.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @param {import('./frontendTypes').SessionEventCommands} commands
 */
export function handleSessionEvent(event, commands = {}) {
    if (!event?.type) return;

    if (RETAINED_SESSION_EVENT_TYPES.has(event.type)) {
        commands.retainEvent?.(event);
    }

    switch (event.type) {
        case EVENT.USER_MESSAGE:
            commands.confirmUserMessage?.();
            break;
        case EVENT.ITERATION:
            commands.finalizeIteration?.();
            break;
        case EVENT.CONTENT:
            if (event.agent_id) commands.updateInProgressIteration?.(event);
            break;
        case EVENT.AGENT_STARTED:
            if (event.agent_id && isRootAgentEvent(event)) commands.setRootAgent?.(event);
            break;
        case EVENT.TURN_END:
            commands.finishTurn?.();
            break;
        default:
            break;
    }
}
