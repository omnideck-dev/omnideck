import { useCallback } from 'react';

import ArtifactsHubView from '../../components/artifacts/ArtifactsHubView.jsx';
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
    useDesktopNavigationState,
} from '../navigation/DesktopNavigation.jsx';
import {
    createArtifactView,
    createFileOutputView,
    createNavigationView,
} from '../desktop/desktopViews.js';
import {
    useDesktopViewCommands,
} from '../desktop/DesktopViewRuntime.jsx';
import useArtifactNavigation from './useArtifactNavigation.js';

/**
 * Commands used by Artifact-owned renderers to cross into Desktop placement.
 *
 * Callers supply artifacts; this adapter is the only layer that translates
 * them into generic serializable View descriptions.
 */
export function useArtifactDesktopActions() {
    const activeConversationId = useActiveConversationId();
    const navigation = useDesktopNavigationCommands();
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
        navigation.openTarget(view.navigationTarget);
    }, [desktop, navigation]);

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
    const { navigationTarget } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const { openArtifact } = useArtifactDesktopActions();
    const { addToast } = useToast();
    const handleArtifactError = useCallback(() => {
        addToast('Could not open the artifact', { type: 'error' });
    }, [addToast]);
    const openArtifactInConversation = useArtifactNavigation({
        navigationTarget,
        navigation,
        openArtifact,
        onError: handleArtifactError,
    });
    const handleViewAction = useCallback((effect) => {
        if (
            effect.actionId === 'open-source-conversation'
            && effect.view.artifact
        ) {
            openArtifactInConversation(effect.view.artifact);
        }
    }, [openArtifactInConversation]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED,
        handleViewAction,
    );
    return null;
}

/** Per-View adapter for the Artifact hub page. */
export default function ArtifactsDesktopView({ view, tabGroupId }) {
    const {
        openArtifact,
        openArtifacts,
    } = useArtifactDesktopActions();
    return (
        <ArtifactsHubView
            conversationId={view.navigationTarget?.conversationId || null}
            onOpenArtifact={(artifact) => openArtifact(artifact, tabGroupId)}
            onClearConversationFilter={() => openArtifacts(null, tabGroupId)}
        />
    );
}
