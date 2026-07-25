import {
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';

import {
    useAppEffectDispatch,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useActiveConversationId,
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../navigation/DesktopNavigation.jsx';
import {
    loadDesktopLayoutSnapshot,
    saveDesktopLayoutSnapshot,
} from './desktopLayoutPersistence.js';
import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import { focusOrderedTabGroupIds } from './desktopLayoutSelectors.js';
import {
    CONVERSATION_VIEW_ID,
    createNavigationView,
    customAppViewId,
} from './desktopViews.js';

function viewForNavigationTarget(layoutState, navigationTarget) {
    if (!navigationTarget) return null;
    if (navigationTarget.kind === 'custom-app') {
        return layoutState.openViewsById[
            customAppViewId(navigationTarget.appSlug)
        ] || null;
    }
    const view = createNavigationView(navigationTarget);
    return view ? layoutState.openViewsById[view.id] || null : null;
}

function restoredNavigationTarget(snapshot) {
    if (!snapshot) return null;
    const { layoutState, navigationTarget } = snapshot;
    if (viewForNavigationTarget(layoutState, navigationTarget)) {
        return navigationTarget;
    }

    for (const tabGroupId of focusOrderedTabGroupIds(layoutState)) {
        const activeViewId = layoutState.tabGroups[tabGroupId].activeViewId;
        const activeView = layoutState.openViewsById[activeViewId];
        if (activeView?.navigationTarget) return activeView.navigationTarget;
    }
    return layoutState.openViewsById[CONVERSATION_VIEW_ID]
        ?.navigationTarget || null;
}

/** Capture one immutable restore snapshot before the layout reducer starts. */
export function useDesktopRestoreSnapshot() {
    return useState(loadDesktopLayoutSnapshot)[0];
}

/**
 * Own restore bootstrap, navigation-to-layout mirroring, and persistence.
 *
 * These effects all synchronize the same Desktop model with application
 * navigation, so keeping them together makes their ordering explicit.
 */
export default function useDesktopShellLifecycle({
    desktopLayout,
    desktopRestore,
}) {
    const { navigationTarget } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const activeConversationId = useActiveConversationId();
    const { loadConversation } = useConversationSessionCommands();
    const dispatchAppEffect = useAppEffectDispatch();
    const [restorationReady, setRestorationReady] = useState(!desktopRestore);
    const restoreStartedRef = useRef(false);
    const preserveRestoredSelectionRef = useRef(Boolean(desktopRestore));
    const navigationView = useMemo(
        () => createNavigationView(navigationTarget),
        [navigationTarget],
    );

    useEffect(() => {
        if (!desktopRestore || restoreStartedRef.current) return undefined;
        restoreStartedRef.current = true;
        let cancelled = false;

        const restoreDesktop = async () => {
            const conversationView = desktopRestore.layoutState
                .openViewsById[CONVERSATION_VIEW_ID];
            const conversationId = conversationView
                ?.navigationTarget?.conversationId;
            let conversationLoaded = true;
            if (conversationId) {
                try {
                    conversationLoaded = Boolean(
                        await loadConversation(conversationId),
                    );
                } catch {
                    conversationLoaded = false;
                }
            }
            if (cancelled) return;

            let nextNavigationTarget = restoredNavigationTarget(desktopRestore);
            if (!conversationLoaded) {
                // Announcing the abandoned Conversation lets feature owners
                // remove dependent Views without restore knowing their types.
                dispatchAppEffect({
                    type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
                    views: conversationView ? [conversationView] : [],
                });
                nextNavigationTarget = {
                    kind: 'chat',
                    conversationId: activeConversationId,
                };
            }
            if (nextNavigationTarget) {
                navigation.openTarget(nextNavigationTarget);
            }
            setRestorationReady(true);
        };
        restoreDesktop();
        return () => {
            cancelled = true;
        };
        // This is a one-time bootstrap from the immutable restored snapshot.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [desktopRestore]);

    useEffect(() => {
        if (!restorationReady) return;
        if (preserveRestoredSelectionRef.current) {
            preserveRestoredSelectionRef.current = false;
            if (
                !navigationView
                || !desktopLayout.model.openViewsById[navigationView.id]
            ) {
                return;
            }
            desktopLayout.commands.openView(
                navigationView,
                DESKTOP_TAB_GROUP_IDS.LEFT,
                { activate: false },
            );
            return;
        }
        if (!navigationView) return;
        desktopLayout.commands.openView(
            navigationView,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        );
    }, [
        desktopLayout.commands.openView,
        navigationView,
        restorationReady,
    ]);

    useEffect(() => {
        if (!restorationReady) return;
        saveDesktopLayoutSnapshot(desktopLayout.model, navigationTarget);
    }, [
        desktopLayout.model,
        navigationTarget,
        restorationReady,
    ]);
}
