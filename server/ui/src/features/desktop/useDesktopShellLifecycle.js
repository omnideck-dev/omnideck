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
    createDesktopLayoutSnapshot,
    loadDesktopLayoutSnapshot,
    writeDesktopLayoutSnapshot,
} from './desktopLayoutPersistence.js';
import { DESKTOP_TAB_GROUP_IDS } from './desktopLayoutReducer.js';
import {
    CONVERSATION_VIEW_ID,
    createNavigationView,
} from './desktopViews.js';

/** Capture one immutable restore snapshot before the layout reducer starts. */
export function useDesktopRestoreSnapshot() {
    return useState(loadDesktopLayoutSnapshot)[0];
}

/**
 * Own restore bootstrap and persistence.
 *
 * Restore loads the Conversation data referenced by the already-restored
 * layout. Focus and location require no reconciliation because both live in
 * that layout.
 */
export default function useDesktopShellLifecycle({
    desktopLayout,
    desktopRestore,
}) {
    const activeConversationId = useActiveConversationId();
    const { loadConversation } = useConversationSessionCommands();
    const dispatchAppEffect = useAppEffectDispatch();
    const [restorationReady, setRestorationReady] = useState(!desktopRestore);
    const restoreStartedRef = useRef(false);
    const persistenceSnapshot = useMemo(
        () => createDesktopLayoutSnapshot(desktopLayout.model),
        [
            desktopLayout.model.floatingViews,
            desktopLayout.model.focusedFloatingViewId,
            desktopLayout.model.focusedTabGroupId,
            desktopLayout.model.fullscreenViewId,
            desktopLayout.model.openViewsById,
            desktopLayout.model.splitRatio,
            desktopLayout.model.tabGroups,
        ],
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

            if (!conversationLoaded) {
                // Announcing the abandoned Conversation lets feature owners
                // remove dependent Views without restore knowing their types.
                dispatchAppEffect({
                    type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
                    views: conversationView ? [conversationView] : [],
                });
                const fallbackView = createNavigationView({
                    kind: 'chat',
                    conversationId: activeConversationId,
                });
                desktopLayout.commands.openView(
                    fallbackView,
                    DESKTOP_TAB_GROUP_IDS.LEFT,
                    // Replace the stale Conversation descriptor without
                    // stealing the location restored from Desktop focus. If
                    // Chat was already active, updating it in place naturally
                    // leaves it active.
                    { activate: false },
                );
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
        writeDesktopLayoutSnapshot(persistenceSnapshot);
    }, [
        persistenceSnapshot,
        restorationReady,
    ]);
}
