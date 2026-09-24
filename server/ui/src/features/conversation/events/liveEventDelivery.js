import { mapConversationEventToActions } from './mapConversationEventToActions.js';

/**
 * Connect canonical live events to their state owners and the application
 * effect dispatcher. Agent text and activity are queued until the next frame
 * so arrival order is preserved without rendering for every stream record.
 *
 * @param {import('./frontendTypes').LiveEventDeliveryOptions} options
 * @returns {import('./frontendTypes').LiveEventDelivery}
 */
export function createLiveEventDelivery({
    dispatch = {},
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
                dispatch.agent?.(action);
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
            const actions = mapConversationEventToActions(event);

            for (const action of actions.session) {
                // A completed turn must expose all preceding agent activity.
                if (action.type === 'FINISH_TURN') {
                    cancelScheduledFlush();
                    flushAgentActions();
                }
                try {
                    dispatch.session?.(action);
                } catch {
                    // Keep later actions and state owners independent.
                }
            }

            // Lifecycle and context state should be visible immediately.
            for (const action of actions.agent.immediate) {
                try {
                    dispatch.agent?.(action);
                } catch {
                    // Keep later actions and state owners independent.
                }
            }

            // Text and activity are delivered together on the next frame.
            if (dispatch.agent && actions.agent.batched.length > 0) {
                pendingAgentActions.push(...actions.agent.batched);
                scheduleAgentFlush();
            }

            for (const action of actions.workspace) {
                try {
                    dispatch.workspace?.(action);
                } catch {
                    // A broken preview must not interrupt other event handling.
                }
            }

            for (const effect of actions.effects) {
                try {
                    dispatch.appEffect?.(effect);
                } catch {
                    // A one-time application effect cannot interrupt delivery.
                }
            }
        },
        flush: flushAgentActions,
        cancel() {
            cancelScheduledFlush();
            pendingAgentActions.length = 0;
        },
    };
}
