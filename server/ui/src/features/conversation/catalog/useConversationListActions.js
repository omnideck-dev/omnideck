import { useCallback, useMemo } from 'react';

import { useToast } from '../../../components/ToastProvider.jsx';
import { MAX_TITLE_LEN } from '../../../components/conversationSections.js';
import { clearChatDraft } from '../../../utils/chatDraftStorage.js';
import { useConversationCatalog } from './ConversationCatalog.jsx';
import useArchivedConversations from './useArchivedConversations.js';

export default function useConversationListActions({ activeConversationId, onNewConversation }) {
    const { addToast } = useToast();
    const {
        setItems,
        handleDelete,
        archiveConversation,
        unarchiveConversation,
        setConversationFolder,
    } = useConversationCatalog();
    const { archived, setArchived, archivedLoaded } = useArchivedConversations();

    const patchConversation = useCallback(async (id, body) => {
        try {
            await fetch(`/api/conversations/sessions/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (_) {
            // The optimistic update already reflects the change; a failed
            // write surfaces on the next refetch rather than blocking the UI.
        }
    }, []);

    const togglePin = useCallback((convo) => {
        const pinned = !convo.pinned;
        setItems((prev) => prev.map((c) => (
            c.conversation_id === convo.conversation_id ? { ...c, pinned } : c
        )));
        patchConversation(convo.conversation_id, { pinned });
    }, [setItems, patchConversation]);

    const renameConversation = useCallback((convo, raw) => {
        // Blank input reverts to the first-message fallback rather than saving
        // an empty title.
        const title = raw.trim().slice(0, MAX_TITLE_LEN);
        setItems((prev) => prev.map((c) => (
            c.conversation_id === convo.conversation_id ? { ...c, title } : c
        )));
        patchConversation(convo.conversation_id, { title });
    }, [setItems, patchConversation]);

    const deleteConversation = useCallback(async (id) => {
        const result = await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            (s) => s.conversation_id !== id,
        );
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return result;
        }
        clearChatDraft(id);
        if (id === activeConversationId) onNewConversation?.();
        return result;
    }, [handleDelete, addToast, activeConversationId, onNewConversation]);

    const moveToFolder = useCallback((convo, folderId) => {
        setConversationFolder(convo.conversation_id, folderId);
    }, [setConversationFolder]);

    const archive = useCallback(async (convo) => {
        const id = convo.conversation_id;
        const result = await archiveConversation(convo);
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return result;
        }
        if (archivedLoaded) {
            setArchived((prev) => (
                prev.some((c) => c.conversation_id === id) ? prev : [result.summary, ...prev]
            ));
        }
        if (id === activeConversationId) onNewConversation?.();
        return result;
    }, [archiveConversation, addToast, archivedLoaded, activeConversationId, onNewConversation]);

    const restoreArchived = useCallback((convo) => {
        const id = convo.conversation_id;
        setArchived((prev) => prev.filter((c) => c.conversation_id !== id));
        unarchiveConversation(convo);
    }, [unarchiveConversation]);

    const deleteArchived = useCallback(async (id) => {
        const result = await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            () => true,
        );
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return result;
        }
        clearChatDraft(id);
        setArchived((prev) => prev.filter((c) => c.conversation_id !== id));
        return result;
    }, [handleDelete, addToast]);

    return useMemo(() => ({
        togglePin,
        renameConversation,
        deleteConversation,
        moveToFolder,
        archiveConversation: archive,
        archived,
        archivedLoaded,
        restoreArchived,
        deleteArchived,
    }), [
        togglePin,
        renameConversation,
        deleteConversation,
        moveToFolder,
        archive,
        archived,
        archivedLoaded,
        restoreArchived,
        deleteArchived,
    ]);
}
