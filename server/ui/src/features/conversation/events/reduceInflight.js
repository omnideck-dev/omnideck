/**
 * Reduce a content delta into the in-flight root-agent iteration.
 *
 * Sub-agent output is excluded because it belongs in the agent activity view,
 * not the main conversation transcript.
 */
export function reduceInflightContent(prev, agentId, depth, content, thinking) {
    if ((depth ?? 0) > 0) return prev;
    const c = content || '';
    const th = thinking || '';
    if (!c && !th) return prev;
    if (!prev || prev.agentId !== agentId) {
        return { agentId, content: c, thinking: th };
    }
    return {
        agentId: prev.agentId,
        content: prev.content + c,
        thinking: prev.thinking + th,
    };
}
