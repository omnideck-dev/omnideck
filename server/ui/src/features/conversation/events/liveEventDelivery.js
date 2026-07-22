import { getAgentEventActions } from './agentEventHandler.js';
import { applyConversationEvent } from './applyConversationEvent.js';
import { runOneTimeEventActions } from './oneTimeEventActions.js';
import { handleSessionEvent } from './sessionEventHandler.js';
import { getWorkspaceEventActions } from './workspaceEventHandler.js';

/**
 * Connect canonical live events to the three state owners and the actions that
 * must run only once. Agent text and activity are queued until the next frame
 * so their arrival order is preserved without rendering for every event.
 */
export function createLiveEventDelivery({
    sessionActions = {},
    onAgentAction,
    onWorkspaceAction,
    oneTimeActions = {},
    requestFrame = requestAnimationFrame,
    cancelFrame = cancelAnimationFrame,
} = {}) {
    const pendingAgentActions = [];
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

    const handlers = {
        session: (event) => handleSessionEvent(event, {
            ...sessionActions,
            // A completed turn must expose all activity that arrived before it.
            finishTurn: () => {
                cancelScheduledFlush();
                flushAgentActions();
                sessionActions.finishTurn?.();
            },
        }),
        agent: (event) => {
            const { immediate, ordered } = getAgentEventActions(event);

            // Lifecycle and context state should be visible immediately.
            for (const action of immediate) {
                try {
                    onAgentAction?.(action);
                } catch {
                    // Keep later actions and state owners independent.
                }
            }

            // Ordered activity populates the agent model for both the root
            // agent and sub-agents. The root transcript is built separately by
            // session state from the same canonical events.
            if (ordered.length === 0 || !onAgentAction) return;
            pendingAgentActions.push(...ordered);
            scheduleAgentFlush();
        },
        workspace: (event) => {
            for (const action of getWorkspaceEventActions(event)) {
                try {
                    onWorkspaceAction?.(action);
                } catch {
                    // A broken preview must not interrupt other event handling.
                }
            }
        },
    };

    return {
        deliver(event) {
            applyConversationEvent(event, handlers);
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
