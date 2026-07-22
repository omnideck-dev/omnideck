/**
 * Accumulate live content deltas into the root agent's current iteration.
 *
 * `projectTurns` consumes complete `iteration` event records. While a response
 * is streaming, however, the backend sends smaller `content` deltas before the
 * completed iteration exists:
 *
 *     null + { content: 'Hel' } + { content: 'lo' }
 *       => { content: 'Hello', thinking: '' }
 *
 * useStreamingChat temporarily appends that accumulated value as an
 * iteration-shaped record before calling projectTurns. Keeping this live-only
 * buffer separate means resumed conversations and finalized live events still
 * use the same deterministic transcript builder.
 *
 * Sub-agent deltas are excluded: this buffer drives the root conversation;
 * sub-agent content belongs in the agent activity view's per-agent log. The
 * buffer resets when the finalized iteration event arrives.
 *
 * @param {import('./frontendTypes').LiveIteration|null} prev
 * @param {string|null} agentId
 * @param {number|null|undefined} depth
 * @param {string|null|undefined} content
 * @param {string|null|undefined} thinking
 * @returns {import('./frontendTypes').LiveIteration|null}
 */
export function accumulateLiveIteration(prev, agentId, depth, content, thinking) {
    if ((depth ?? 0) > 0) return prev;
    const c = content || '';
    const th = thinking || '';
    if (!c && !th) return prev;
    if (!agentId) return prev;
    if (!prev || prev.agentId !== agentId) {
        return { agentId, content: c, thinking: th };
    }
    return {
        agentId: prev.agentId,
        content: prev.content + c,
        thinking: prev.thinking + th,
    };
}
