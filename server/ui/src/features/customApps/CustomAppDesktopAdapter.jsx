import { useCallback } from 'react';

import CustomAppHost from '../../components/apps/CustomAppHost.jsx';
import {
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import useCustomAppDesktopViews from './useCustomAppDesktopViews.js';
import styles from './CustomAppDesktopView.module.css';

/**
 * Installs catalog reconciliation and Custom App view-action handling.
 *
 * This is a named, headless feature effect—not a provider around unrelated
 * Desktop content.
 */
export function CustomAppDesktopEffects() {
    useCustomAppDesktopViews();
    return null;
}

/** Per-View adapter from a Custom App descriptor to its domain renderer. */
export default function CustomAppDesktopView({ view, active }) {
    const navigation = useDesktopNavigationCommands();
    const { composeFromSource } = useConversationSessionCommands();

    const openChat = useCallback(() => {
        navigation.openChat();
    }, [navigation]);
    const composeChat = useCallback(({ text, context }) => {
        // Conversation owns draft formatting; this adapter supplies only the
        // source identity and source-authored payload.
        composeFromSource({
            title: view.app.title,
            text,
            context,
        });
        navigation.openChat();
    }, [composeFromSource, navigation, view.app.title]);

    return (
        <div
            className={styles.view}
            data-testid="custom-app-view"
        >
            <CustomAppHost
                app={view.app}
                reloadSignal={view.reloadSignal}
                active={active}
                onOpenChat={openChat}
                onComposeChat={composeChat}
            />
        </div>
    );
}
