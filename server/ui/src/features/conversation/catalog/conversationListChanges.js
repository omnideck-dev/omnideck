/**
 * @typedef {import('../../app/activityMessages.generated').ConversationSummary} ConversationSummary
 */

/**
 * @param {ConversationSummary[]} list
 * @param {ConversationSummary} summary
 * @returns {ConversationSummary[]}
 */
export function upsertConversation(list, summary) {
    const index = list.findIndex((c) => c.conversation_id === summary.conversation_id);
    if (index === -1) return [summary, ...list];
    const next = [...list];
    next[index] = { ...list[index], ...summary };
    return next;
}

/**
 * @param {ConversationSummary[]} list
 * @param {string} conversationId
 * @returns {ConversationSummary[]}
 */
export function removeConversation(list, conversationId) {
    return list.some((c) => c.conversation_id === conversationId)
        ? list.filter((c) => c.conversation_id !== conversationId)
        : list;
}

/**
 * Apply a server-side chat change to the active list or the archived list.
 *
 * @param {ConversationSummary[]} list
 * @param {{ conversation: ConversationSummary, archived: boolean }} change
 * @param {boolean} listIsArchived
 * @returns {ConversationSummary[]}
 */
export function applyConversationChange(list, change, listIsArchived) {
    return change.archived === listIsArchived
        ? upsertConversation(list, change.conversation)
        : removeConversation(list, change.conversation.conversation_id);
}
