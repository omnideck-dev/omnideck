import { mapConversationEventToActions } from './mapConversationEventToActions.js';
import { CONVERSATION_EVENT_TYPES as EVENT } from './eventTypes.js';

/** @param {string|null|undefined} timestamp */
function eventTime(timestamp) {
    const parsed = timestamp ? Date.parse(timestamp) : NaN;
    return Number.isFinite(parsed) ? parsed : Date.now();
}

/**
 * Build the reducer actions needed to restore one saved conversation.
 *
 * Persisted conversation events use the same agent event actions as the live
 * stream. Browser and terminal data is restored explicitly from its bounded
 * sidecars. Presentation effects are deliberately not part of this plan.
 *
 * @param {import('./frontendTypes').ConversationRestoreData|null|undefined} data
 * @returns {import('./frontendTypes').ConversationRestorePlan}
 */
export function getConversationRestorePlan(data) {
    const events = Array.isArray(data?.events) ? data.events : [];
    /** @type {Array<import('./frontendTypes').AgentAction>} */
    const agentActions = [];
    /** @type {Array<import('./frontendTypes').WorkspaceAction>} */
    const workspaceActions = [];
    /** @type {Map<string, number>} */
    const unfinishedAgents = new Map();

    for (const event of events) {
        if (!event?.type) continue;

        const actions = mapConversationEventToActions(event);
        agentActions.push(...actions.agent.immediate, ...actions.agent.batched);
        workspaceActions.push(...actions.workspace);

        const agentId = event.agent_id || null;
        if (event.type === EVENT.AGENT_STARTED && agentId) {
            unfinishedAgents.set(agentId, eventTime(event.timestamp));
        } else if (event.type === EVENT.AGENT_COMPLETED && agentId) {
            unfinishedAgents.delete(agentId);
        }

        if (agentId && unfinishedAgents.has(agentId)) {
            unfinishedAgents.set(agentId, eventTime(event.timestamp));
        }
    }

    // A process can stop before writing agent_completed. Restored agents must
    // not remain visually active forever, so freeze them at their last event.
    for (const [agentId, timestamp] of unfinishedAgents) {
        agentActions.push({
            type: 'AGENT_COMPLETED',
            agentId,
            status: 'stopped',
            timestamp,
        });
    }

    for (const tab of (data?.browserTabs || [])) {
        if (!tab?.agent_id) continue;
        const parsedTabId = Number(tab.tab_id);
        workspaceActions.push({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: tab.agent_id,
            snapshot: {
                url: tab.url,
                title: tab.title,
                screenshot: tab.screenshot,
                tabId: Number.isFinite(parsedTabId) ? parsedTabId : null,
                openTabIds: null,
                agentId: tab.agent_id,
            },
        });
    }

    for (const [agentId, entries] of Object.entries(data?.terminal || {})) {
        for (const entry of (entries || [])) {
            workspaceActions.push({
                type: 'UPDATE_TERMINAL',
                agentId,
                event: { ...entry, agentId },
            });
        }
    }

    return {
        agentActions,
        workspaceActions,
    };
}
