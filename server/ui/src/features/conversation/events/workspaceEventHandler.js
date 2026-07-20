import { CONVERSATION_EVENT_TYPES as EVENT } from './eventTypes.js';

function eventDetails(event) {
    const {
        id: _id,
        timestamp: _timestamp,
        conversation_id: _conversationId,
        agent_id: _agentId,
        agent_name: _agentName,
        depth: _depth,
        ...details
    } = event;
    return details;
}

/** Convert one canonical event into workspace reducer actions. */
export function getWorkspaceEventActions(event) {
    if (!event?.type) return [];
    const agentId = event.agent_id || null;

    switch (event.type) {
        case EVENT.BROWSER_SCREENSHOT:
            return [{
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId,
                snapshot: {
                    url: event.url,
                    title: event.title,
                    screenshot: event.screenshot,
                    tabId: event.tab_id ?? null,
                    openTabIds: event.open_tab_ids ?? null,
                    agentId,
                },
            }];
        case EVENT.TERMINAL_OUTPUT:
            return [{
                type: 'UPDATE_TERMINAL',
                agentId,
                event: { ...eventDetails(event), agentId },
            }];
        case EVENT.DESKTOP_ACTIVE:
            return [{ type: 'UPDATE_DESKTOP_ACTIVE', agentId }];
        case EVENT.GENERATION_PREVIEW:
            return [{
                type: 'UPDATE_GENERATION_PREVIEW',
                agentId,
                preview: { ...eventDetails(event), agentId },
            }];
        default:
            return [];
    }
}
