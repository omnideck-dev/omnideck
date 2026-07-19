/**
 * Flatten a live stream message into the persisted event shape used by the
 * conversation projections.
 */
export function normalizeLiveEvent(data) {
    const payload = data?.payload;
    if (!payload || typeof payload !== 'object') return null;
    const { type, ...rest } = payload;
    return {
        id: data.id || `live_${Date.now()}_${Math.random().toString(36).slice(2)}`,
        type,
        timestamp: data.timestamp || new Date().toISOString(),
        conversation_id: data.conversation_id || null,
        agent_id: data.agent_id || null,
        agent_name: data.agent_name || null,
        depth: data.depth ?? 0,
        ...rest,
    };
}
