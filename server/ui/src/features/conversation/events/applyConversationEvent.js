/** @type {Array<keyof import('./frontendTypes').EventHandlers>} */
const STATE_HANDLER_NAMES = ['session', 'agent', 'workspace'];

/**
 * Give one canonical conversation event to each state handler.
 *
 * Each handler is isolated so a broken preview update, for example, cannot stop
 * the session or agent model from seeing the same event. One-time actions are
 * intentionally outside this function and are called only by live intake.
 *
 * @param {import('./conversationEvents.generated').ConversationEvent|null|undefined} event
 * @param {import('./frontendTypes').EventHandlers} handlers
 * @returns {Array<{handlerName: keyof import('./frontendTypes').EventHandlers, error: unknown}>}
 */
export function applyConversationEvent(event, handlers = {}) {
    if (!event?.type) return [];

    /** @type {Array<{handlerName: keyof import('./frontendTypes').EventHandlers, error: unknown}>} */
    const failures = [];
    for (const handlerName of STATE_HANDLER_NAMES) {
        const handle = handlers[handlerName];
        if (typeof handle !== 'function') continue;
        try {
            handle(event);
        } catch (error) {
            failures.push({ handlerName, error });
        }
    }
    return failures;
}
