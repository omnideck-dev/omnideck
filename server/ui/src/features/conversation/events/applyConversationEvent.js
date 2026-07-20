const STATE_HANDLERS = ['session', 'agent', 'workspace'];

/**
 * Give one canonical conversation event to each state owner.
 *
 * Each owner is isolated so a broken preview update, for example, cannot stop
 * the session or agent model from seeing the same event. One-time actions are
 * intentionally outside this function and are called only by live intake.
 */
export function applyConversationEvent(event, handlers = {}) {
    if (!event?.type) return [];

    const failures = [];
    for (const owner of STATE_HANDLERS) {
        const handle = handlers[owner];
        if (typeof handle !== 'function') continue;
        try {
            handle(event);
        } catch (error) {
            failures.push({ owner, error });
        }
    }
    return failures;
}
