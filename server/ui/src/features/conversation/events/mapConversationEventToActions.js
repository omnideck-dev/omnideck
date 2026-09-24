import { getAgentEventActions } from './agentEventActions.js';
import { getConversationEventEffects } from './conversationEventEffects.js';
import { getSessionEventActions } from './sessionEventActions.js';
import { getWorkspaceEventActions } from './workspaceEventActions.js';

/**
 * Map one canonical conversation event to state-owner actions and application
 * effects. Live delivery and restoration can share the same interpretation;
 * restoration simply ignores the one-time effects.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {import('./frontendTypes').ConversationEventActions}
 */
export function mapConversationEventToActions(event) {
    if (!event?.type) {
        return {
            session: [],
            agent: { immediate: [], batched: [] },
            workspace: [],
            effects: [],
        };
    }

    /** @type {Array<import('./frontendTypes').SessionAction>} */
    let session = [];
    /** @type {{immediate: Array<import('./frontendTypes').AgentAction>, batched: Array<import('./frontendTypes').AgentAction>}} */
    let agent = { immediate: [], batched: [] };
    /** @type {Array<import('./frontendTypes').WorkspaceAction>} */
    let workspace = [];
    /** @type {Array<import('../../app/appEffects.types').AppEffect>} */
    let effects = [];

    // Keep interpretation failures local to their state owner. These builders
    // are pure, but malformed input in one must not hide the event from others.
    try {
        session = getSessionEventActions(event);
    } catch {
        // Ignore invalid session data and continue with the other owners.
    }
    try {
        agent = getAgentEventActions(event);
    } catch {
        // Ignore invalid agent data and continue with the other owners.
    }
    try {
        workspace = getWorkspaceEventActions(event);
    } catch {
        // Ignore invalid workspace data and continue with the other owners.
    }
    try {
        effects = getConversationEventEffects(event);
    } catch {
        // A malformed one-time effect must not hide persistent state updates.
    }

    return {
        session,
        agent,
        workspace,
        effects,
    };
}
