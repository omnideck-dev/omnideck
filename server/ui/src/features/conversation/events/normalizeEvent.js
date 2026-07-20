/**
 * Flatten a live stream envelope into the same top-level shape stored in
 * events.jsonl and consumed by the transcript builder.
 *
 * The wire protocol keeps event-specific fields under `payload` and transport
 * metadata beside it:
 *
 *     { agent_id: 'root.1', depth: 0,
 *       payload: { type: 'iteration', content: 'Hello' } }
 *
 * The normalized record lifts the payload fields next to that metadata:
 *
 *     { agent_id: 'root.1', depth: 0,
 *       type: 'iteration', content: 'Hello', ... }
 *
 * Live events without an id or timestamp receive UI-local fallbacks. Resumed
 * events are already flat, so they do not pass through this function.
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
