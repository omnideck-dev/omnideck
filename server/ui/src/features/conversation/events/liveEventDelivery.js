import { getConversationEventActions } from './conversationEventActions.js';
import { runOneTimeEventActions } from './oneTimeEventActions.js';

/**
 * Connect canonical live events to the three state owners and the actions that
 * must run only once. Agent text and activity are queued until the next frame
 * so their arrival order is preserved without rendering for every event.
 *
 * @param {import('./frontendTypes').LiveEventDeliveryOptions} options
 * @returns {import('./frontendTypes').LiveEventDelivery}
 */
export function createLiveEventDelivery({
    onSessionAction,
    onAgentAction,
    onWorkspaceAction,
    oneTimeActions = {},
    requestFrame = requestAnimationFrame,
    cancelFrame = cancelAnimationFrame,
} = {}) {
    /** @type {Array<import('./frontendTypes').AgentAction>} */
    const pendingAgentActions = [];
    /** @type {number|null} */
    let frameId = null;

    const flushAgentActions = () => {
        frameId = null;
        for (const action of pendingAgentActions.splice(0)) {
            try {
                onAgentAction?.(action);
            } catch {
                // One failed dispatch must not drop later queued activity.
            }
        }
    };

    const scheduleAgentFlush = () => {
        if (frameId === null) frameId = requestFrame(flushAgentActions);
    };

    const cancelScheduledFlush = () => {
        if (frameId !== null) cancelFrame(frameId);
        frameId = null;
    };

    return {
        /** @param {import('./conversationEvents.generated').ConversationEvent} event */
        deliver(event) {
            const actions = getConversationEventActions(event);

            for (const action of actions.session) {
                // A completed turn must expose all preceding agent activity.
                if (action.type === 'FINISH_TURN') {
                    cancelScheduledFlush();
                    flushAgentActions();
                }
                try {
                    onSessionAction?.(action);
                } catch {
                    // Keep later actions and state owners independent.
                }
            }

            // Lifecycle and context state should be visible immediately.
            for (const action of actions.agent.immediate) {
                try {
                    onAgentAction?.(action);
                } catch {
                    // Keep later actions and state owners independent.
                }
            }

            // Text and activity retain arrival order across animation frames.
            if (onAgentAction && actions.agent.ordered.length > 0) {
                pendingAgentActions.push(...actions.agent.ordered);
                scheduleAgentFlush();
            }

            for (const action of actions.workspace) {
                try {
                    onWorkspaceAction?.(action);
                } catch {
                    // A broken preview must not interrupt other event handling.
                }
            }

            try {
                runOneTimeEventActions(event, oneTimeActions);
            } catch {
                // A one-time UI action cannot interrupt event delivery.
            }
        },
        flush: flushAgentActions,
        cancel() {
            cancelScheduledFlush();
            pendingAgentActions.length = 0;
        },
    };
}
