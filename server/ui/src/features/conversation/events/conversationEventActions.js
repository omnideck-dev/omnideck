import { getAgentEventActions } from './agentEventActions.js';
import { getSessionEventActions } from './sessionEventActions.js';
import { getWorkspaceEventActions } from './workspaceEventActions.js';

/**
 * Build the complete state-change plan for one canonical conversation event.
 * Each state owner has one explicit section, so live delivery and restoration
 * can share interpretation without a callback registry or global event bus.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @returns {import('./frontendTypes').ConversationEventActions}
 */
export function getConversationEventActions(event) {
    if (!event?.type) {
        return { session: [], agent: { immediate: [], ordered: [] }, workspace: [] };
    }

    /** @type {Array<import('./frontendTypes').SessionAction>} */
    let session = [];
    /** @type {{immediate: Array<import('./frontendTypes').AgentAction>, ordered: Array<import('./frontendTypes').AgentAction>}} */
    let agent = { immediate: [], ordered: [] };
    /** @type {Array<import('./frontendTypes').WorkspaceAction>} */
    let workspace = [];

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

    return { session, agent, workspace };
}
