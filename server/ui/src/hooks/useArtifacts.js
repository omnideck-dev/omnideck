import { useCallback } from 'react';

import useListPanel from './useListPanel.js';

/**
 * Fetch + manage the artifacts list. Thin wrapper over useListPanel:
 * the global hub passes no conversationId; the in-conversation drawer passes one
 * (and drops it to show "all"). Adds artifact-specific delete + prune helpers.
 *
 * @param {object} options
 * @param {string|null} [options.conversationId] - scope to one conversation
 */
export default function useArtifacts({ conversationId = null } = {}) {
    const qs = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
    const panel = useListPanel(`/api/artifacts${qs}`, {
        getId: (a) => a.id,
        transform: (data) => data.artifacts || [],
    });
    const { handleDelete, refetch } = panel;

    // Remove one artifact; optionally also unlink its file on disk.
    const removeArtifact = useCallback((id, { deleteFile = false } = {}) => {
        const endpoint = `/api/artifacts/${id}${deleteFile ? '?delete_file=true' : ''}`;
        return handleDelete(id, endpoint, (a) => a.id !== id);
    }, [handleDelete]);

    // Drop every entry whose file is gone (scoped to the conversation if set).
    const pruneMissing = useCallback(async () => {
        try {
            await fetch(`/api/artifacts/prune-missing${qs}`, { method: 'POST' });
        } catch (_) {
            // ignore — refetch reflects whatever actually changed
        }
        refetch();
    }, [qs, refetch]);

    return { ...panel, removeArtifact, pruneMissing };
}
