import {
    useCallback,
    useState,
} from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import Sidebar from '../../components/Sidebar.jsx';
import { useToast } from '../../components/ToastProvider.jsx';
import useAgentNetworkCounts from '../agent/useAgentNetworkCounts.js';
import { useAppSettings } from '../app/AppSettings.jsx';
import useArtifactNavigation from '../artifacts/useArtifactNavigation.js';
import {
    useConversationSession,
} from '../conversation/session/ConversationSession.jsx';
import { useCustomApps } from '../customApps/CustomApps.jsx';
import useCustomAppDesktop from '../customApps/useCustomAppDesktop.js';
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../navigation/DesktopNavigation.jsx';
import useWorkspacePreview from '../workspace/useWorkspacePreview.jsx';
import DesktopPages from './DesktopPages.jsx';
import GlobalOverlays from './GlobalOverlays.jsx';
import MainSurface from './MainSurface.jsx';
import useDesktopDock from './useDesktopDock.jsx';
import styles from '../../App.module.css';

/** Coordinates desktop destinations without owning feature data. */
export default function Desktop() {
    const { destination } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const view = destination.kind;
    const selectedAgentId = view === 'network' ? destination.agentId : null;
    const { profilesHook, features } = useAppData();
    const { defaultProfileId, homeAppSlug } = useAppSettings();
    const customApps = useCustomApps();
    const { addToast } = useToast();

    const [muted, setMuted] = useState(false);
    const [userDesktopOpen, setUserDesktopOpen] = useState(false);

    const {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        sendMessage,
        sendNudge,
        stopGeneration,
        newConversation: startNewConversation,
        activeConversationId,
        draft,
        setDraft,
        savePreviewState,
        conversationProfileId,
        setConversationProfileId,
        pendingAudio,
        clearPendingAudio,
    } = useConversationSession();

    const { preview, browser } = useWorkspacePreview({
        conversationId: activeConversationId,
        isStreaming,
        selectedAgentId,
        savePreviewState,
    });
    const dock = useDesktopDock({ customApp: customApps.openApp, preview });

    const selectedProfileId = conversationProfileId ?? defaultProfileId;
    const handleProfileChange = useCallback(
        (id) => setConversationProfileId(id),
        [setConversationProfileId],
    );

    const handleSend = useCallback((message, attachments) => {
        if (isStreaming) {
            if (!stopRequested) sendNudge(message);
        } else {
            sendMessage(message, attachments, selectedProfileId);
        }
    }, [isStreaming, selectedProfileId, sendMessage, sendNudge, stopRequested]);

    const openDesktop = useCallback(async () => {
        if (userDesktopOpen) return;
        try {
            const response = await fetch('/api/desktop/start', { method: 'POST' });
            const data = await response.json();
            if (data.running) setUserDesktopOpen(true);
            else addToast(data.error || 'Desktop is not available', { type: 'error' });
        } catch {
            addToast('Could not reach the server', { type: 'error' });
        }
    }, [addToast, userDesktopOpen]);

    const customAppDesktop = useCustomAppDesktop({
        customApps,
        destination,
        dock,
        homeAppSlug,
        navigation,
        setDraft,
    });

    const newConversation = useCallback(async (options) => {
        const conversationId = await startNewConversation(options);
        navigation.openChat(conversationId);
        if (customApps.isOpen) dock.showCustomApp(customApps.openApp.slug);
        return conversationId;
    }, [customApps.isOpen, customApps.openApp, dock.showCustomApp, navigation, startNewConversation]);

    const composeInNewConversation = useCallback(
        (text) => newConversation({ draft: text }),
        [newConversation],
    );

    const handleLoadConversation = useCallback(async (conversationId) => {
        const loaded = await navigation.openConversation(conversationId);
        if (loaded && customApps.isOpen) dock.showCustomApp(customApps.openApp.slug);
        return loaded;
    }, [customApps.isOpen, customApps.openApp, dock.showCustomApp, navigation]);

    const openWorkspacePreview = useCallback((item) => {
        const itemId = `file:${item.path || item.filename}`;
        preview.openFile(item);
        dock.showWorkspacePreview(itemId);
        if (view === 'custom-app') navigation.openChat();
    }, [dock.showWorkspacePreview, navigation, preview.openFile, view]);

    const closeDockItem = useCallback((itemId) => {
        if (itemId === dock.customAppItemId) customAppDesktop.closeCustomApp();
        else preview.closeTab(itemId);
    }, [customAppDesktop.closeCustomApp, dock.customAppItemId, preview.closeTab]);

    const handleArtifactError = useCallback(() => {
        addToast('Could not open the artifact', { type: 'error' });
    }, [addToast]);
    const openArtifactInConversation = useArtifactNavigation({
        destination,
        navigation,
        openWorkspacePreview,
        onError: handleArtifactError,
    });

    const agentCounts = useAgentNetworkCounts();
    const handleOpenNetwork = useCallback(() => navigation.openNetwork(), [navigation]);
    const handleCloseNetwork = useCallback(() => navigation.openChat(), [navigation]);
    const handleSelectAgent = useCallback((agentId) => navigation.openAgent(agentId), [navigation]);

    const handlePanelToggle = useCallback((panel) => {
        if (!panel) {
            navigation.openChat();
            return;
        }
        const command = {
            settings: navigation.openSettings,
            routines: navigation.openRoutines,
            artifacts: navigation.openArtifacts,
            agents: navigation.openAgents,
            apps: customAppDesktop.openCustomApps,
            home: customAppDesktop.openHome,
        }[panel];
        command?.();
    }, [customAppDesktop.openCustomApps, customAppDesktop.openHome, navigation]);

    const dockExpanded = view === 'custom-app' && customApps.isOpen;
    const includeCustomAppInDock = view === 'chat' || dockExpanded;
    const dockVisible = dockExpanded
        || (view === 'chat' && dock.items.length > 0)
        || (view === 'network' && Boolean(selectedAgentId) && preview.tabs.length > 0);
    const activeSidebarPanel = view === 'custom-app'
        ? (customApps.isHome ? 'home' : null)
        : (['settings', 'routines', 'artifacts', 'agents', 'apps', 'home'].includes(view) ? view : null);

    const dockActions = {
        openCustomApps: customAppDesktop.openCustomApps,
        dockCustomApp: customAppDesktop.dockCustomApp,
        expandCustomApp: () => {
            if (customApps.openApp) customAppDesktop.expandCustomApp(customApps.openApp);
        },
        composeFromCustomApp: customAppDesktop.composeFromCustomApp,
        closeCustomApp: customAppDesktop.closeCustomApp,
        closeDockItem,
        toggleCustomAppHome: customAppDesktop.toggleCustomAppHome,
    };

    return (
        <div className={styles.desktop}>
            <div className={styles.bodyRow}>
                <Sidebar
                    activePanel={activeSidebarPanel}
                    onNewConversation={newConversation}
                    audio={pendingAudio}
                    muted={muted}
                    onToggleMute={() => setMuted((current) => !current)}
                    onAudioEnded={clearPendingAudio}
                    desktopEnabled={features.desktop}
                    onOpenDesktop={openDesktop}
                    onLoadConversation={handleLoadConversation}
                    activeConversationId={activeConversationId}
                    onPanelToggle={handlePanelToggle}
                    customAppsEnabled={features.custom_apps}
                    homeAppEnabled={Boolean(homeAppSlug)}
                />

                <div className={styles.mainContent}>
                    <DesktopPages
                        view={view}
                        actions={{
                            composeInNewConversation,
                            openArtifactInConversation,
                            expandCustomApp: customAppDesktop.expandCustomApp,
                            openCustomAppInDock: customAppDesktop.openCustomAppInDock,
                            openCustomApps: customAppDesktop.openCustomApps,
                            clearUnavailableHome: customAppDesktop.clearUnavailableHome,
                        }}
                    />
                    <MainSurface
                        view={view}
                        selectedAgentId={selectedAgentId}
                        dockVisible={dockVisible}
                        dockExpanded={dockExpanded}
                        includeCustomAppInDock={includeCustomAppInDock}
                        dock={dock}
                        preview={preview}
                        browser={browser}
                        customApps={customApps}
                        agentCounts={agentCounts}
                        session={{
                            turns,
                            stalled,
                            isStreaming,
                            stopRequested,
                            sendNudge,
                            stopGeneration,
                            activeConversationId,
                            draft,
                            setDraft,
                        }}
                        selectedProfileId={selectedProfileId}
                        profileRevision={profilesHook.revision}
                        actions={{
                            closeNetwork: handleCloseNetwork,
                            openNetwork: handleOpenNetwork,
                            selectAgent: handleSelectAgent,
                            openPreview: openWorkspacePreview,
                            send: handleSend,
                            changeProfile: handleProfileChange,
                            ...dockActions,
                        }}
                    />
                </div>
            </div>

            <GlobalOverlays
                userDesktopOpen={userDesktopOpen}
                closeUserDesktop={() => setUserDesktopOpen(false)}
                preview={preview}
                browser={browser}
            />
        </div>
    );
}
