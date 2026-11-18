/** Add a message to the queue once. */
export function queueMessage(state, message) {
    if (state.queue.some((item) => item.id === message.id)) return state;
    return { ...state, queue: [...state.queue, message] };
}

/** Take a message out of the queue; a returned one waits for the composer. */
export function dropQueued(state, id, returned) {
    const message = state.queue.find((item) => item.id === id);
    if (!message) return state;
    return {
        ...state,
        queue: state.queue.filter((item) => item.id !== id),
        returned: returned ? [...state.returned, message] : state.returned,
    };
}

/** Forget returned messages the composer has taken back. */
export function consumeReturned(state, ids) {
    return { ...state, returned: state.returned.filter((item) => !ids.includes(item.id)) };
}

/** The run hands back unread messages before it ends, so anything left is stale. */
export function clearQueue(state) {
    return { ...state, queue: [] };
}
