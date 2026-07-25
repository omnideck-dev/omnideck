import {
    createContext,
    useCallback,
    useContext,
    useMemo,
} from 'react';

import {
    useAppEffectDispatch,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useActiveConversationId,
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import { DESKTOP_TAB_GROUP_IDS } from '../desktop/desktopLayoutReducer.js';
import {
    useDesktopViewCatalog,
    useDesktopViewCommands,
    useFocusedViewId,
} from '../desktop/DesktopViewRuntime.jsx';
import { createNavigationView } from '../desktop/desktopViews.js';

const DesktopNavigationCommandsContext = createContext(null);

/**
 * Translate application navigation intent directly into Desktop Views.
 *
 * Desktop Layout is the only store of what is open and focused. This provider
 * owns no parallel "current target" state; it is a narrow command vocabulary
 * for callers that should not construct View descriptors themselves.
 */
export function DesktopNavigationProvider({ children }) {
    const activeConversationId = useActiveConversationId();
    const { loadConversation } = useConversationSessionCommands();
    const desktop = useDesktopViewCommands();
    const dispatchAppEffect = useAppEffectDispatch();

    const openTarget = useCallback((nextTarget) => {
        if (!nextTarget?.kind) return false;

        if (nextTarget.kind === 'custom-app') {
            if (!nextTarget.appSlug) return false;
            // A slug cannot become a View until the domain catalog resolves
            // it. Custom Apps owns that short-lived deferred intent.
            dispatchAppEffect({
                type: APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED,
                appSlug: nextTarget.appSlug,
            });
            return true;
        }

        // artifactId is a deferred Artifact-domain key, not part of the
        // Conversation View's durable navigation identity.
        const {
            artifactId = null,
            ...viewTarget
        } = nextTarget;
        const view = createNavigationView(viewTarget);
        if (!view) return false;
        desktop.openView(view, {
            tabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
        });
        if (artifactId) {
            dispatchAppEffect({
                type: APP_EFFECT_TYPES.OPEN_ARTIFACT_REQUESTED,
                artifactId,
                conversationId: viewTarget.conversationId || null,
            });
        }
        return true;
    }, [desktop, dispatchAppEffect]);

    const openChat = useCallback(
        (conversationId = activeConversationId) => openTarget({
            kind: 'chat',
            conversationId: conversationId || null,
        }),
        [activeConversationId, openTarget],
    );
    const openNetwork = useCallback(
        (agentId = null) => openTarget({
            kind: 'network',
            conversationId: activeConversationId || null,
            agentId,
        }),
        [activeConversationId, openTarget],
    );
    const openAgent = useCallback(
        (agentId) => openNetwork(agentId),
        [openNetwork],
    );
    const openSettings = useCallback(
        (tab = null) => openTarget({ kind: 'settings', tab }),
        [openTarget],
    );
    const openAgents = useCallback(
        (profileId = null) => openTarget({ kind: 'agents', profileId }),
        [openTarget],
    );
    const openRoutines = useCallback(
        (routineId = null, runId = null) => openTarget({
            kind: 'routines',
            routineId,
            runId,
        }),
        [openTarget],
    );
    const openArtifacts = useCallback(
        (conversationId = null) => openTarget({
            kind: 'artifacts',
            conversationId,
        }),
        [openTarget],
    );
    const openApps = useCallback(
        () => openTarget({ kind: 'apps' }),
        [openTarget],
    );
    const openCustomApp = useCallback(
        (appSlug) => openTarget({ kind: 'custom-app', appSlug }),
        [openTarget],
    );

    const openConversation = useCallback(async (
        conversationId,
        { artifactId = null } = {},
    ) => {
        if (conversationId !== activeConversationId) {
            const loaded = await loadConversation(conversationId);
            if (!loaded) return false;
        }
        openTarget({
            kind: 'chat',
            conversationId,
            ...(artifactId ? { artifactId } : {}),
        });
        return true;
    }, [activeConversationId, loadConversation, openTarget]);

    const commands = useMemo(() => ({
        openTarget,
        openChat,
        openNetwork,
        openAgent,
        openConversation,
        openSettings,
        openAgents,
        openRoutines,
        openArtifacts,
        openApps,
        openCustomApp,
    }), [
        openAgent,
        openAgents,
        openApps,
        openArtifacts,
        openChat,
        openConversation,
        openCustomApp,
        openNetwork,
        openRoutines,
        openSettings,
        openTarget,
    ]);

    return (
        <DesktopNavigationCommandsContext.Provider value={commands}>
            {children}
        </DesktopNavigationCommandsContext.Provider>
    );
}

export function useDesktopNavigationCommands() {
    const commands = useContext(DesktopNavigationCommandsContext);
    if (commands === null) {
        throw new Error(
            'useDesktopNavigationCommands must be used within DesktopNavigationProvider',
        );
    }
    return commands;
}

/**
 * Derive application location from the focused View rather than a second
 * mutable store. Views without navigation identity (for example an Artifact
 * file or Browser) intentionally return null.
 */
export function useCurrentNavigationTarget() {
    const focusedViewId = useFocusedViewId();
    const { openViewsById } = useDesktopViewCatalog();
    return openViewsById[focusedViewId]?.navigationTarget || null;
}
