export function queueMessage(state, message) {
    if (state.queue.some((item) => item.id === message.id)) return state;
    return { ...state, queue: [...state.queue, message] };
}

export function dropQueued(state, id, returned) {
    const message = state.queue.find((item) => item.id === id);
    if (!message) return state;
    return {
        ...state,
        queue: state.queue.filter((item) => item.id !== id),
        returned: returned ? [...state.returned, message] : state.returned,
    };
}

export function consumeReturned(state, ids) {
    return { ...state, returned: state.returned.filter((item) => !ids.includes(item.id)) };
}

export function clearQueue(state) {
    return { ...state, queue: [] };
}
