import { createContext, useContext, useCallback } from 'react';

import useListPanel from '../hooks/useListPanel.js';

/**
 * Ask the backend to generate and persist a title for a conversation from its
 * first message. Returns the title, or null on any failure — title generation
 * is best-effort, so the sidebar keeps the first-message fallback if it fails.
 */
async function _generateTitle(conversationId, firstMessage) {
    try {
        const resp = await fetch(`/api/conversations/sessions/${conversationId}/title`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ first_message: firstMessage }),
        });
        if (!resp.ok) return null;
        const data = await resp.json();
        return data.title || null;
    } catch (_) {
        return null;
    }
}

/**
 * Owns the sidebar's recent-conversations list. The list is fetched once on
 * mount and then mutated locally: new conversations are pushed in optimistically
 * the moment they start, titles are patched in place when generation returns,
 * and pin/rename/delete edit the array directly. There is no server-originated
 * list mutation left to discover, so the list never refetches after load.
 */
const ConversationsContext = createContext(null);

export function ConversationsProvider({ children }) {
    // No refreshSignal: the list loads once on mount and is kept current by the
    // mutations below rather than refetching.
    const panel = useListPanel('/api/conversations/sessions', {
        getId: (s) => s.conversation_id,
    });
    const { setItems } = panel;

    // Add a conversation that just started its first turn to the list. The
    // events-first backend has already persisted it, so this only mirrors it
    // into the in-memory list (so it appears without a refetch) and fills in
    // its title once generation returns. Deduped by id so a double-send or a
    // later resume can't insert it twice.
    const addStartedConversation = useCallback(({ conversationId, firstMessage }) => {
        setItems((prev) => (
            prev.some((c) => c.conversation_id === conversationId)
                ? prev
                : [{
                    conversation_id: conversationId,
                    first_message: firstMessage,
                    title: '',
                    started_at: new Date().toISOString(),
                    turn_count: 1,
                    pinned: false,
                }, ...prev]
        ));
        _generateTitle(conversationId, firstMessage).then((title) => {
            if (!title) return;
            setItems((prev) => prev.map((c) => (
                c.conversation_id === conversationId ? { ...c, title } : c
            )));
        });
    }, [setItems]);

    // Persist a file as the open + active tab in a conversation's preview state
    // so reopening that conversation restores it. Conversation-scoped; doesn't
    // touch the in-memory list.
    const focusFileInConversation = useCallback(async (conversationId, path) => {
        await fetch(`/api/conversations/sessions/${conversationId}/preview-state/focus-file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
    }, []);

    // Archive a conversation: drop it from the active list optimistically and
    // move it into the archive on the server. Archiving is the reversible
    // alternative to delete — the conversation can be restored from the
    // archived view. Returns the removed summary so callers can surface it in
    // the archived list without a refetch.
    const archiveConversation = useCallback(async (conversationId) => {
        let removed = null;
        setItems((prev) => {
            removed = prev.find((c) => c.conversation_id === conversationId) || null;
            return prev.filter((c) => c.conversation_id !== conversationId);
        });
        try {
            await fetch(`/api/conversations/sessions/${conversationId}/archive`, {
                method: 'POST',
            });
        } catch (_) {
            // The optimistic removal already reflects the change; a failed
            // write surfaces on the next reload rather than blocking the UI.
        }
        return removed;
    }, [setItems]);

    // Restore an archived conversation back into the active list. Takes the
    // archived summary so the row can reappear among the recents without a
    // refetch.
    const unarchiveConversation = useCallback(async (summary) => {
        const id = summary.conversation_id;
        setItems((prev) => (
            prev.some((c) => c.conversation_id === id) ? prev : [summary, ...prev]
        ));
        try {
            await fetch(`/api/conversations/sessions/${id}/unarchive`, {
                method: 'POST',
            });
        } catch (_) {
            // Optimistic insert stands; a failed write surfaces on next reload.
        }
    }, [setItems]);

    const value = {
        ...panel,
        addStartedConversation,
        focusFileInConversation,
        archiveConversation,
        unarchiveConversation,
    };
    return (
        <ConversationsContext.Provider value={value}>
            {children}
        </ConversationsContext.Provider>
    );
}

/** Returns the recent-conversations list and its mutators. Throws outside the provider. */
export function useConversations() {
    const value = useContext(ConversationsContext);
    if (value === null) {
        throw new Error('useConversations must be used inside <ConversationsProvider>');
    }
    return value;
}
