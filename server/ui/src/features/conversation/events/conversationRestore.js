import { getAgentEventActions } from './agentEventHandler.js';
import { CONVERSATION_EVENT_TYPES as EVENT, isRootAgentEvent } from './eventTypes.js';

/** @param {string|null|undefined} timestamp */
function eventTime(timestamp) {
    const parsed = timestamp ? Date.parse(timestamp) : NaN;
    return Number.isFinite(parsed) ? parsed : Date.now();
}

/**
 * Build the reducer actions needed to restore one saved conversation.
 *
 * Persisted conversation events use the same agent event handler as the live
 * stream. Browser, terminal, and open-file state is restored explicitly from
 * its bounded sidecars because it is workspace state, not conversation history.
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
    let lastRootAgentId = null;

    for (const event of events) {
        if (!event?.type) continue;

        const { immediate, ordered } = getAgentEventActions(event);
        agentActions.push(...immediate, ...ordered);

        const agentId = event.agent_id || null;
        if (event.type === EVENT.AGENT_STARTED && agentId) {
            unfinishedAgents.set(agentId, eventTime(event.timestamp));
            if (isRootAgentEvent(event)) lastRootAgentId = agentId;
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

    if (lastRootAgentId) {
        const openPaths = Array.isArray(data?.previewState?.open_files)
            ? data.previewState.open_files
            : [];
        for (const path of openPaths) {
            if (typeof path !== 'string' || !path) continue;
            workspaceActions.push({
                type: 'OPEN_FILE',
                agentId: lastRootAgentId,
                item: {
                    type: 'file_output',
                    filename: path.split('/').pop() || path,
                    path,
                },
            });
        }
    }

    return {
        agentActions,
        workspaceActions,
        activeTab: lastRootAgentId && typeof data?.previewState?.active_tab === 'string'
            ? data.previewState.active_tab
            : null,
    };
}
