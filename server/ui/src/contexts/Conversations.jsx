import { createContext, useContext, useCallback } from 'react';

import useListPanel from '../hooks/useListPanel.js';

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
    // mutators below rather than refetching.
    const panel = useListPanel('/api/conversations/sessions', {
        getId: (s) => s.conversation_id,
    });
    const { setItems } = panel;

    // Push a just-started conversation to the top so it appears the instant the
    // user sends, without waiting for the turn to finish. Deduped by id so a
    // double-send or a later resume can't insert it twice.
    const insertConversation = useCallback((summary) => {
        setItems((prev) => (
            prev.some((c) => c.conversation_id === summary.conversation_id)
                ? prev
                : [summary, ...prev]
        ));
    }, [setItems]);

    // Replace a conversation's title in place — used when title generation
    // returns. A no-op if the conversation isn't in the list.
    const patchConversationTitle = useCallback((id, title) => {
        setItems((prev) => prev.map((c) => (
            c.conversation_id === id ? { ...c, title } : c
        )));
    }, [setItems]);

    const value = { ...panel, insertConversation, patchConversationTitle };
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
