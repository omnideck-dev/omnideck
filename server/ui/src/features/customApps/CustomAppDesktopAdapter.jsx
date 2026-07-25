import {
    useCallback,
    useMemo,
} from 'react';

import CustomAppHost from '../../components/apps/CustomAppHost.jsx';
import {
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import { DESKTOP_TAB_GROUP_IDS } from '../desktop/desktopLayoutReducer.js';
import {
    useDesktopViewCatalog,
    useDesktopViewCommands,
} from '../desktop/DesktopViewRuntime.jsx';
import {
    createCustomAppView,
    customAppSlugForView,
    customAppViewId,
} from './customAppDesktopViews.js';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import { useCustomApps } from './CustomApps.jsx';
import useCustomAppDesktopViews from './useCustomAppDesktopViews.js';
import styles from './CustomAppDesktopView.module.css';

/** Translate Custom App catalog records into generic Desktop View commands. */
export function useCustomAppDesktopActions() {
    const desktopModel = useDesktopViewCatalog();
    const desktopCommands = useDesktopViewCommands();
    const openApp = useCallback((
        app,
        tabGroupId = DESKTOP_TAB_GROUP_IDS.LEFT,
    ) => {
        const existing = desktopModel.openViewsById[
            customAppViewId(app.slug)
        ];
        desktopCommands.openView(
            createCustomAppView(app, existing?.reloadSignal || 0),
            { tabGroupId },
        );
    }, [
        desktopCommands.openView,
        desktopModel.openViewsById,
    ]);

    return useMemo(() => ({ openApp }), [openApp]);
}

/**
 * Installs catalog reconciliation and Custom App view-action handling.
 *
 * This is a named, headless feature effect—not a provider around unrelated
 * Desktop content.
 */
export function CustomAppDesktopEffects() {
    const { openApp } = useCustomAppDesktopActions();
    useCustomAppDesktopViews({ openApp });
    return null;
}

/** Per-View adapter from a Custom App descriptor to its domain renderer. */
export default function CustomAppDesktopView({ view, visible }) {
    const customApps = useCustomApps();
    const navigation = useDesktopNavigationCommands();
    const { composeFromSource } = useConversationSessionCommands();
    // Persisted Views carry only the slug. The catalog remains the owner of
    // the live app record used by the iframe host.
    const app = view.app
        || customApps.catalog.findBySlug(customAppSlugForView(view));

    const openChat = useCallback(() => {
        navigation.openChat();
    }, [navigation]);
    const composeChat = useCallback(({ text, context }) => {
        // Conversation owns draft formatting; this adapter supplies only the
        // source identity and source-authored payload.
        composeFromSource({
            title: app.title,
            text,
            context,
        });
        navigation.openChat();
    }, [app?.title, composeFromSource, navigation]);

    // The headless reconcile effect closes missing restored apps once the
    // catalog is authoritative. Render nothing during that short resolution
    // window instead of dereferencing stale persisted domain data.
    if (!app) return null;

    return (
        <div
            className={styles.view}
            data-testid="custom-app-view"
        >
            <CustomAppHost
                app={app}
                reloadSignal={view.reloadSignal || 0}
                visible={visible}
                onOpenChat={openChat}
                onComposeChat={composeChat}
            />
        </div>
    );
}
