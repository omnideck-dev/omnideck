import { useCallback } from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import Sidebar from '../../components/Sidebar.jsx';
import {
    useActiveConversationId,
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import useGraphicalDesktopOverlay from
    '../remoteDesktop/useGraphicalDesktopOverlay.js';
import DesktopDomainEffects from './DesktopDomainEffects.jsx';
import DesktopViewContent from './DesktopViewContent.jsx';
import DesktopLayout from './DesktopLayout.jsx';
import GlobalOverlays from './GlobalOverlays.jsx';
import {
    DesktopViewRuntimeProvider,
} from './DesktopViewRuntime.jsx';
import useDesktopLayout from './useDesktopLayout.jsx';
import useDesktopShellLifecycle, {
    useDesktopRestoreSnapshot,
} from './useDesktopShellLifecycle.js';
import useDesktopViewInteractions from './useDesktopViewInteractions.js';
import { createNavigationView } from './desktopViews.js';
import styles from '../../App.module.css';

const INITIAL_CHAT_VIEW = createNavigationView({
    kind: 'chat',
    conversationId: null,
});

/**
 * Owns the Desktop Layout hook and installs the adapter boundary around it.
 *
 * Keeping the reducer owner outside the adapters lets every domain use the
 * same generic View command interface without moving domain data into Desktop.
 */
export default function Desktop() {
    const desktopRestore = useDesktopRestoreSnapshot();
    const desktopLayout = useDesktopLayout({
        initialView: INITIAL_CHAT_VIEW,
        initialLayoutState: desktopRestore?.layoutState || null,
    });

    return (
        <DesktopViewRuntimeProvider desktopLayout={desktopLayout}>
            <DesktopDomainEffects />
            <DesktopShell
                desktopLayout={desktopLayout}
                desktopRestore={desktopRestore}
            />
        </DesktopViewRuntimeProvider>
    );
}

/**
 * Coordinates application-wide navigation and View placement.
 *
 * Domain render data and lifecycle policy are intentionally absent here.
 * Desktop emits generic View lifecycle/action events; feature owners translate
 * those events and each rendered adapter reads its own domain contexts.
 */
function DesktopShell({ desktopLayout, desktopRestore }) {
    const navigation = useDesktopNavigationCommands();
    const { features } = useAppData();
    const graphicalDesktop = useGraphicalDesktopOverlay();

    const activeConversationId = useActiveConversationId();
    const {
        newConversation: startNewConversation,
    } = useConversationSessionCommands();
    useDesktopShellLifecycle({ desktopLayout, desktopRestore });

    const newConversation = useCallback(async (options) => {
        const conversationId = await startNewConversation(options);
        navigation.openChat(conversationId);
        return conversationId;
    }, [navigation, startNewConversation]);

    const handleLoadConversation = useCallback(async (conversationId) => (
        navigation.openConversation(conversationId)
    ), [navigation]);

    const {
        getViewActions,
        handleCloseView,
        handleFocusView,
        handleSelectView,
    } = useDesktopViewInteractions({
        desktopLayout,
        navigation,
    });

    return (
        <div className={styles.desktop}>
            <div className={styles.bodyRow}>
                <Sidebar
                    onNewConversation={newConversation}
                    desktopEnabled={features.desktop}
                    onOpenDesktop={graphicalDesktop.openOverlay}
                    onLoadConversation={handleLoadConversation}
                    activeConversationId={activeConversationId}
                />

                <div className={styles.mainContent}>
                    <DesktopLayout
                        model={desktopLayout.model}
                        commands={desktopLayout.commands}
                        onSelectView={handleSelectView}
                        onFocusView={handleFocusView}
                        onCloseView={handleCloseView}
                        getViewActions={getViewActions}
                        renderView={(view, { active, tabGroupId }) => (
                            <DesktopViewContent
                                view={view}
                                active={active}
                                tabGroupId={tabGroupId}
                            />
                        )}
                    />
                </div>
            </div>

            <GlobalOverlays
                userDesktopOpen={graphicalDesktop.open}
                closeUserDesktop={graphicalDesktop.closeOverlay}
            />
        </div>
    );
}
