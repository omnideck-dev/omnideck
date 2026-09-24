// Persisted per-conversation chat drafts, shared by the composer (saves as
// the user types) and the conversations sidebar (clears on permanent
// delete). Kept storage-access failures local to this module so callers
// never need to guard against a throwing localStorage.

const DRAFT_KEY_PREFIX = 'omnideck_chat_draft_v1:';

/** Read a conversation's unsent draft text, if any was saved on this browser. */
export function loadChatDraft(conversationId) {
    if (!conversationId) return '';
    try {
        // The `localStorage` getter itself (not just its methods) can throw
        // — e.g. Safari private mode raises SecurityError just accessing it.
        if (typeof localStorage === 'undefined') return '';
        return localStorage.getItem(DRAFT_KEY_PREFIX + conversationId) || '';
    } catch {
        return '';
    }
}

/** Save (or clear, once empty) a conversation's unsent draft text. */
export function saveChatDraft(conversationId, text) {
    if (!conversationId) return;
    try {
        if (typeof localStorage === 'undefined') return;
        if (text) {
            localStorage.setItem(DRAFT_KEY_PREFIX + conversationId, text);
        } else {
            localStorage.removeItem(DRAFT_KEY_PREFIX + conversationId);
        }
    } catch {
        // Storage unavailable/full — draft persistence is best-effort.
    }
}

/** Remove a conversation's persisted draft — call when it's permanently deleted. */
export function clearChatDraft(conversationId) {
    saveChatDraft(conversationId, '');
}
