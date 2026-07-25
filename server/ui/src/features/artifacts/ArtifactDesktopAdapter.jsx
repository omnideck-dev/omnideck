import {
    useCallback,
    useEffect,
    useMemo,
} from 'react';

import ArtifactsHubView from '../../components/artifacts/ArtifactsHubView.jsx';
import FilePreview from '../../components/FilePreview.jsx';
import { useToast } from '../../components/ToastProvider.jsx';
import {
    useAppEffectSubscription,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useActiveConversationId,
} from '../conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import {
    createNavigationView,
    navigationTargetForView,
} from '../navigation/desktopNavigationViews.js';
import {
    useDesktopViewCatalog,
    useDesktopViewCommands,
} from '../desktop/DesktopViewRuntime.jsx';
import {
    createArtifactView,
    createFileOutputView,
} from './artifactDesktopViews.js';
import useArtifactNavigation from './useArtifactNavigation.js';

async function fetchJson(url, signal) {
    try {
        const response = await fetch(url, { signal });
        if (response.status === 404) return { status: 'missing' };
        if (!response.ok) return { status: 'error' };
        return {
            status: 'found',
            value: await response.json(),
        };
    } catch (error) {
        return error.name === 'AbortError'
            ? { status: 'aborted' }
            : { status: 'error' };
    }
}

/** Resolve one persisted Artifact key without teaching persistence its schema. */
async function resolveArtifactView(view, signal) {
    const {
        resourceId,
        resourcePath,
        conversationId,
    } = view.identity;
    let result;
    if (resourceId) {
        result = await fetchJson(
            `/api/artifacts/${encodeURIComponent(resourceId)}`,
            signal,
        );
    } else if (resourcePath) {
        const query = conversationId
            ? `?conversation_id=${encodeURIComponent(conversationId)}`
            : '';
        const collection = await fetchJson(`/api/artifacts${query}`, signal);
        result = collection.status === 'found'
            ? {
                status: 'found',
                value: (collection.value.artifacts || []).find(
                    (artifact) => artifact.path === resourcePath,
                ) || null,
            }
            : collection;
        if (result.status === 'found' && !result.value) {
            result = { status: 'missing' };
        }
    } else {
        result = { status: 'missing' };
    }

    if (
        result.status === 'found'
        && result.value?.status === 'missing'
    ) {
        return { status: 'missing' };
    }
    return result;
}

function useArtifactViewRehydration() {
    const { openViews } = useDesktopViewCatalog();
    const desktop = useDesktopViewCommands();
    const unresolvedViews = useMemo(
        () => openViews.filter(
            (view) => view.type === 'artifact-file' && !view.artifact,
        ),
        [openViews],
    );

    useEffect(() => {
        if (!unresolvedViews.length) return undefined;
        const controller = new AbortController();
        let cancelled = false;

        Promise.all(unresolvedViews.map(async (view) => ({
            view,
            result: await resolveArtifactView(view, controller.signal),
        }))).then((resolutions) => {
            if (cancelled) return;
            const views = [];
            const closeViewIds = [];
            for (const { view, result } of resolutions) {
                if (result.status === 'missing') {
                    closeViewIds.push(view.id);
                    continue;
                }
                // A transport failure is not proof the durable Artifact was
                // deleted. Keep the View unresolved instead of closing it; a
                // later catalog change retries without creating a polling loop.
                if (result.status !== 'found') continue;
                const hydrated = createArtifactView(result.value);
                if (!hydrated) {
                    closeViewIds.push(view.id);
                    continue;
                }
                // Placement keys must remain stable while the Artifact domain
                // replaces durable identity with its live runtime record.
                views.push({ ...hydrated, id: view.id });
            }
            if (views.length || closeViewIds.length) {
                desktop.syncViews({ views, closeViewIds });
            }
        });

        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [desktop.syncViews, unresolvedViews]);
}

/**
 * Commands used by Artifact-owned renderers to cross into Desktop placement.
 *
 * Callers supply artifacts; this adapter is the only layer that translates
 * them into generic serializable View descriptions.
 */
export function useArtifactDesktopActions() {
    const activeConversationId = useActiveConversationId();
    const desktop = useDesktopViewCommands();

    const openArtifact = useCallback((artifact, tabGroupId = null) => {
        const view = createArtifactView(artifact);
        if (!view) return;
        desktop.openView(view, {
            tabGroupId: tabGroupId || desktop.preferredTabGroupId(),
        });
    }, [desktop]);

    const openFileOutput = useCallback((item) => {
        const view = createFileOutputView(item, activeConversationId);
        if (!view) return;
        desktop.openView(view, {
            tabGroupId: desktop.preferredTabGroupId(),
        });
    }, [activeConversationId, desktop]);

    const openArtifacts = useCallback((conversationId = null, tabGroupId) => {
        const view = createNavigationView({
            kind: 'artifacts',
            conversationId,
        });
        desktop.openView(view, {
            tabGroupId: tabGroupId || desktop.preferredTabGroupId(),
        });
    }, [desktop]);

    return {
        openArtifact,
        openArtifacts,
        // This named convenience command keeps conversation renderers from
        // constructing an Artifact navigation target themselves.
        openConversationArtifacts: openArtifacts,
        openFileOutput,
    };
}

/**
 * Handles Artifact navigation restoration and Artifact-specific view actions.
 *
 * Desktop emits a generic action request; this owner decides what an Artifact
 * action means.
 */
export function ArtifactDesktopEffects() {
    useArtifactViewRehydration();
    const navigation = useDesktopNavigationCommands();
    const { openArtifact } = useArtifactDesktopActions();
    const { addToast } = useToast();
    const handleArtifactError = useCallback(() => {
        addToast('Could not open the artifact', { type: 'error' });
    }, [addToast]);
    const openArtifactInConversation = useArtifactNavigation({
        navigation,
        openArtifact,
        onError: handleArtifactError,
    });
    const handleViewAction = useCallback((effect) => {
        if (effect.actionId !== 'open-source-conversation') return;
        const artifact = effect.view.artifact;
        if (!artifact?.id || !artifact.conversation_id) {
            // A declared View action must either work or fail visibly. This
            // also guards restored/legacy descriptors that predate the
            // factory-level action validation.
            handleArtifactError();
            return;
        }
        openArtifactInConversation(artifact);
    }, [handleArtifactError, openArtifactInConversation]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED,
        handleViewAction,
    );
    return null;
}

/**
 * Render one hydrated Artifact file.
 *
 * Restored Views remain blank only while the headless Artifact effect resolves
 * their durable key. This renderer needs no Desktop commands or placement.
 */
export function ArtifactFileDesktopView({ view }) {
    // Restored file Views render after the headless domain effect resolves
    // their durable key. Avoid handing an incomplete record to FilePreview.
    return view.artifact ? <FilePreview item={view.artifact} /> : null;
}

/** Render the Artifact library and adapt its actions to Desktop commands. */
export default function ArtifactsHubDesktopView({ view, tabGroupId }) {
    const {
        openArtifact,
        openArtifacts,
    } = useArtifactDesktopActions();
    return (
        <ArtifactsHubView
            conversationId={
                navigationTargetForView(view)?.conversationId || null
            }
            onOpenArtifact={(artifact) => openArtifact(artifact, tabGroupId)}
            onClearConversationFilter={() => openArtifacts(null, tabGroupId)}
        />
    );
}
