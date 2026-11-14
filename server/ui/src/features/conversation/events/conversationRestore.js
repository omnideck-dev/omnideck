import { mapConversationEventToActions } from './mapConversationEventToActions.js';
import { CONVERSATION_EVENT_TYPES as EVENT, isRootAgentEvent } from './eventTypes.js';

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
    // not remain visually active forever, except when the server explicitly
    // reports that this conversation still has a run we are about to follow.
    if (!data?.activeRun) {
        for (const [agentId, timestamp] of unfinishedAgents) {
            agentActions.push({
                type: 'AGENT_COMPLETED',
                agentId,
                status: 'stopped',
                timestamp,
            });
        }
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

/**
 * A process can stop before writing agent_completed. When the server reports
 * no active run, add the missing completion for each root agent left open, so
 * the transcript treats its turn as finished.
 *
 * @param {Array<import('./conversationEvents.generated').ConversationEvent>} events
 * @returns {Array<import('./conversationEvents.generated').ConversationEvent>}
 */
export function closeInterruptedTurns(events) {
    /** @type {Map<string, import('./conversationEvents.generated').ConversationEvent>} Each open agent's latest event. */
    const open = new Map();
    for (const event of events) {
        if (!event.agent_id) continue;
        if (event.type === EVENT.AGENT_STARTED && isRootAgentEvent(event)) open.set(event.agent_id, event);
        else if (event.type === EVENT.AGENT_COMPLETED) open.delete(event.agent_id);
        else if (open.has(event.agent_id)) open.set(event.agent_id, event);
    }
    if (open.size === 0) return events;
    return [...events, ...Array.from(open, ([agentId, last]) => ({
        id: `_interrupted_${agentId}`,
        timestamp: last.timestamp,
        conversation_id: last.conversation_id,
        type: /** @type {const} */ ('agent_completed'),
        agent_id: agentId,
        agent_name: last.agent_name || '',
        depth: 0,
        status: /** @type {const} */ ('stopped'),
    }))];
}
