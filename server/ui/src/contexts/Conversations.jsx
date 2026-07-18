import { createContext, useContext, useCallback, useEffect, useState } from 'react';

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

    // Folders are a small, separately-loaded list. Like the conversation list
    // they load once and are kept current by the mutations below.
    const [folders, setFolders] = useState([]);
    useEffect(() => {
        let cancelled = false;
        fetch('/api/conversations/folders')
            .then((r) => (r.ok ? r.json() : []))
            .then((data) => { if (!cancelled) setFolders(data); })
            .catch(() => {});
        return () => { cancelled = true; };
    }, []);

    // Create a folder and add it to the in-memory list. Returns the created
    // folder (with its server-assigned id) so callers can immediately file a
    // conversation into it.
    const createFolder = useCallback(async (name) => {
        try {
            const resp = await fetch('/api/conversations/folders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name }),
            });
            if (!resp.ok) return null;
            const folder = await resp.json();
            setFolders((prev) => [...prev, folder]);
            return folder;
        } catch (_) {
            return null;
        }
    }, []);

    const renameFolder = useCallback((folderId, name) => {
        setFolders((prev) => prev.map((f) => (f.id === folderId ? { ...f, name } : f)));
        fetch(`/api/conversations/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        }).catch(() => {});
    }, []);

    const setFolderIcon = useCallback((folderId, icon) => {
        setFolders((prev) => prev.map((f) => (f.id === folderId ? { ...f, icon } : f)));
        fetch(`/api/conversations/folders/${folderId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ icon }),
        }).catch(() => {});
    }, []);

    // Delete a folder: drop it from the list and clear the folder tag from any
    // loaded conversations so they fall back to the date-grouped listing —
    // mirroring what the server does to their metadata.
    const deleteFolder = useCallback((folderId) => {
        setFolders((prev) => prev.filter((f) => f.id !== folderId));
        setItems((prev) => prev.map((c) => (
            c.folder_id === folderId ? { ...c, folder_id: null } : c
        )));
        fetch(`/api/conversations/folders/${folderId}`, { method: 'DELETE' }).catch(() => {});
    }, [setItems]);

    // File a conversation into a folder (or remove it when folderId is null).
    // The server owns the rule that filing into a folder unpins the chat; here
    // we just send the folder and optimistically mirror the resulting state
    // (folder set, pin cleared) so the row moves without waiting on the write.
    const setConversationFolder = useCallback((conversationId, folderId) => {
        setItems((prev) => prev.map((c) => (
            c.conversation_id === conversationId
                ? { ...c, folder_id: folderId, pinned: folderId ? false : c.pinned }
                : c
        )));
        fetch(`/api/conversations/sessions/${conversationId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder_id: folderId }),
        }).catch(() => {});
    }, [setItems]);

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
                    folder_id: null,
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
        folders,
        createFolder,
        renameFolder,
        setFolderIcon,
        deleteFolder,
        setConversationFolder,
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
