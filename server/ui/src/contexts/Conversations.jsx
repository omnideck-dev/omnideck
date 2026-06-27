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

    // A brand-new conversation just started its first turn. The events-first
    // backend has already persisted it, so mirror it into the list now (so it
    // appears without a refetch) and fill in its title once generation returns.
    // Deduped by id so a double-send or a later resume can't insert it twice.
    const startConversation = useCallback(({ conversationId, firstMessage }) => {
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

    const value = { ...panel, startConversation };
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
