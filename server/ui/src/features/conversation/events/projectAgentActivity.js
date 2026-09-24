import { TRANSCRIPT_ITEM_KINDS as ITEM } from './eventTypes.js';

/**
 * Project one root agent's activity from the conversation transcript.
 *
 * Root output already lives in the session's canonical event projection, so
 * retaining a second copy in AgentState only creates synchronization work.
 * Sub-agent activity remains owned by AgentState because it is intentionally
 * excluded from the main transcript.
 *
 * @param {Array<import('./frontendTypes').ConversationTurn>|null|undefined} turns
 * @param {string|null|undefined} agentId
 * @returns {Array<Record<string, unknown>>}
 */
export function projectAgentActivity(turns, agentId) {
    if (!agentId || !Array.isArray(turns)) return [];
    const entries = [];

    for (const turn of turns) {
        if (turn?.agentId !== agentId || !Array.isArray(turn.children)) continue;
        for (const child of turn.children) {
            if (child.kind === ITEM.ITERATION) {
                if (child.thinking) {
                    entries.push({ type: 'thinking', thinking: child.thinking });
                }
                if (child.content) {
                    entries.push({ type: 'content', content: child.content });
                }
                for (const toolCall of (child.toolCalls || [])) {
                    entries.push({
                        type: 'tool_call',
                        name: toolCall.name,
                        arguments: toolCall.arguments || null,
                    });
                }
            } else if (child.kind === ITEM.SPAWN_REQUESTED) {
                entries.push({
                    type: 'spawn_requested',
                    correlationId: child.correlationId,
                });
            } else if (child.kind === ITEM.FILE_OUTPUT) {
                entries.push({
                    type: 'file_output',
                    filename: child.filename,
                    content_type: child.contentType,
                    path: child.path,
                    timestamp: child.timestamp,
                });
            } else if (child.kind === ITEM.COMPACTION) {
                entries.push({
                    type: 'compaction',
                    stats: child.stats,
                    summaryText: child.summaryText,
                    userIntentSummary: child.userIntentSummary,
                    timestamp: child.timestamp,
                });
            } else if (child.kind === ITEM.ERROR) {
                entries.push({
                    type: 'error',
                    message: child.message,
                });
            }
        }
    }

    return entries;
}
