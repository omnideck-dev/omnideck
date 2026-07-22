import { useState, useCallback } from 'react';

import {
    useConversationSession,
} from '../../features/conversation/session/ConversationSession.jsx';
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../../features/navigation/DesktopNavigation.jsx';
import SetupWizard from '../../components/SetupWizard.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import {
    useConversationCatalog,
} from '../../features/conversation/catalog/ConversationCatalog.jsx';
import Sidebar from '../../components/Sidebar.jsx';
import { useAgentState } from '../agent/AgentState.jsx';
import useAgentNetworkCounts from '../agent/useAgentNetworkCounts.js';
import useCustomApps from '../customApps/useCustomApps.jsx';
import { useToast } from '../../components/ToastProvider.jsx';
import useWorkspacePreview from '../workspace/useWorkspacePreview.jsx';
import useDesktopSetup from './useDesktopSetup.js';
import MainSurface from './MainSurface.jsx';
import FeatureSurfaces from './FeatureSurfaces.jsx';
import GlobalOverlays from './GlobalOverlays.jsx';
import styles from '../../App.module.css';

/**
 * Main app shell. Preview data (browser screenshots, terminal output, etc.)
 * lives in the workspace owner and follows the active root or selected agent.
 */
export default function DesktopShell() {
    const agentState = useAgentState();
    const { destination } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const view = destination.kind;
    const selectedAgentId = view === 'network' ? destination.agentId : null;

    // ── UI-only state (not duplicated in the reducer) ───────────────
    const [muted, setMuted] = useState(false);
    const [userDesktopOpen, setUserDesktopOpen] = useState(false);
    const { profilesHook, features } = useAppData();
    const { focusFileInConversation } = useConversationCatalog();
    const {
        setupComplete,
        finishSetup,
        defaultProfileId,
        homeAppSlug,
        setHomeAppSlug,
    } = useDesktopSetup();

    const { addToast } = useToast();

    const {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        sendMessage,
        sendNudge,
        stopGeneration,
        newConversation: chatNewConversation,
        activeConversationId,
        draft,
        setDraft,
        savePreviewState,
        conversationProfileId,
        setConversationProfileId,
        toolsRefreshSignal,
        pendingAudio,
        clearPendingAudio,
    } = useConversationSession();

    const { preview, browser } = useWorkspacePreview({
        conversationId: activeConversationId,
        isStreaming,
        selectedAgentId,
        savePreviewState,
    });

    const { catalog: customAppsCatalog, workspace: customApps } = useCustomApps({
        enabled: features.custom_apps,
        setupComplete,
        homeAppSlug,
        setHomeAppSlug,
        navigation,
        preview,
        setDraft,
        destinationKind: view,
    });

    // The profile for the open conversation: its own pick, or the default.
    const selectedProfileId = conversationProfileId ?? defaultProfileId;
    const handleProfileChange = useCallback(
        (id) => setConversationProfileId(id),
        [setConversationProfileId],
    );

    const handleSend = useCallback((message, attachments) => {
        if (isStreaming) {
            if (!stopRequested) sendNudge(message);
        } else {
            // The new-conversation case (optimistic sidebar insert + title
            // generation) is handled by the onConversationStarted callback,
            // which sendMessage fires when it starts a fresh conversation.
            sendMessage(message, attachments, selectedProfileId);
        }
    }, [sendMessage, sendNudge, isStreaming, stopRequested, selectedProfileId]);

    const openDesktop = useCallback(async () => {
        if (userDesktopOpen) return;
        try {
            const res = await fetch('/api/desktop/start', { method: 'POST' });
            const data = await res.json();
            if (data.running) {
                setUserDesktopOpen(true);
            } else {
                addToast(data.error || 'Desktop is not available', { type: 'error' });
            }
        } catch {
            addToast('Could not reach the server', { type: 'error' });
        }
    }, [userDesktopOpen, addToast]);

    const newConversation = useCallback(async (opts) => {
        const conversationId = await chatNewConversation(opts);
        // Surface the chat — otherwise a panel/network view stays stacked on
        // top and the new conversation is invisible. The session command also
        // resets the agent and workspace owners.
        if (customApps.isOpen) customApps.openChat();
        else navigation.resetToChat(conversationId);
    }, [
        chatNewConversation,
        customApps.isOpen,
        customApps.openChat,
        navigation,
    ]);

    // Open a fresh chat with the composer pre-seeded (e.g. composing a routine
    // from the routines view). The chat state seeds the draft in the same batch
    // as the new conversation id.
    const composeInNewChat = useCallback((text) => newConversation({ draft: text }), [newConversation]);

    // Loading a conversation has to surface the chat too, same as newConversation.
    const handleLoadConversation = useCallback(async (conversationId) => {
        const loaded = await navigation.openConversation(conversationId);
        if (loaded && customApps.isOpen) customApps.openChat();
        return loaded;
    }, [customApps.isOpen, customApps.openChat, navigation]);

    // Open an artifact's source conversation with that file focused. Persist the
    // focus into preview_state first, then either open the file immediately (if
    // the conversation is already active) or load it normally — the resume path
    // restores the focused file. Reuses the single conversation opener; adds no
    // second open path.
    const openArtifactInConversation = useCallback(async (artifact) => {
        const { conversation_id: conversationId, path, filename, content_type: contentType } = artifact;
        try {
            await focusFileInConversation(conversationId, path);
        } catch (_) {
            // Best-effort: navigate even if the focus write fails; the file
            // just won't be pre-opened.
        }
        if (conversationId === activeConversationId) {
            customApps.openPreview({ filename, content_type: contentType, path });
            if (!customApps.isOpen) navigation.openChat(conversationId);
            return;
        }
        handleLoadConversation(conversationId);
    }, [
        activeConversationId,
        customApps.isOpen,
        customApps.openPreview,
        handleLoadConversation,
        focusFileInConversation,
        navigation,
    ]);

    // ── Which layout to show ───────────────────────────────────────────
    // `view` picks exactly one shell surface. The workspace surface has its own
    // full/split presentation state while the app iframe stays mounted. Each is a
    // full replacement of the main column, so they're mutually exclusive by
    // construction — no view can stay stacked under another.
    //
    //   chat (default) — chat + preview panels. Always shows the root agent's
    //     conversation. When sub-agents spawn, a network indicator appears so
    //     the user can navigate to the network.
    //   workspace — a full app, or chat + a global app/conversation-preview rail.
    //   settings / routines — full-screen panels opened from the sidebar.
    //   network — full-screen agent graph. Click a card to drill into an
    //     agent's detail view (network destination + agentId); close to return
    //     to chat.
    //
    // Agent detail is a sub-state of the serializable network destination.

    const agentCounts = useAgentNetworkCounts();

    // Opening the network lands on the graph, so drop any stale selection
    // (it would otherwise reopen straight into an old agent's detail view).
    const handleOpenNetwork = useCallback(() => {
        navigation.openNetwork();
    }, [navigation]);

    const handleCloseNetwork = useCallback(() => {
        customApps.restoreChat();
    }, [customApps.restoreChat]);

    // Drill straight into a sub-agent's activity view — e.g. from a
    // SpawnCard row in the chat.
    const handleSelectAgent = useCallback((agentId) => {
        navigation.openAgent(agentId);
    }, [navigation]);

    // Sidebar nav (settings/routines). A null panel means toggle back to chat.
    const handlePanelToggle = useCallback((panel) => {
        if (!panel) {
            customApps.restoreChat();
            return;
        }
        const command = {
            settings: navigation.openSettings,
            routines: navigation.openRoutines,
            artifacts: navigation.openArtifacts,
            agents: navigation.openAgents,
            apps: navigation.openApps,
            home: navigation.openHome,
        }[panel];
        command?.();
    }, [customApps.restoreChat, navigation]);

    const openPreviewFromChat = useCallback((item) => {
        customApps.openPreview(item);
    }, [customApps.openPreview]);

    const workspaceVisible = view === 'workspace' && customApps.isOpen;
    const workspaceSplit = workspaceVisible && customApps.layout === 'split';
    const activeSidebarPanel = view === 'workspace'
        ? (customApps.layout === 'full' && customApps.origin === 'home' ? 'home' : null)
        : (['settings', 'routines', 'artifacts', 'agents', 'apps', 'home'].includes(view) ? view : null);

    // Preview column rides alongside chat, or alongside an agent's detail view.
    const hasPreview = preview.tabs.length > 0
        && !workspaceVisible
        && (view === 'chat' || (view === 'network' && !!selectedAgentId));

    // Show setup wizard if setup is not complete
    if (setupComplete === false) {
        return (
            <SetupWizard onComplete={() => {
                finishSetup();
                profilesHook.refresh();
            }} />
        );
    }

    // Still loading setup status
    if (setupComplete === null) {
        return null;
    }

    return (
        <div className={styles.appShell}>
            <div className={styles.bodyRow}>
                {/* Navigation sidebar */}
                <Sidebar
                    activePanel={activeSidebarPanel}
                    onNewConversation={newConversation}
                    audio={pendingAudio}
                    muted={muted}
                    onToggleMute={() => setMuted((m) => !m)}
                    onAudioEnded={clearPendingAudio}
                    desktopEnabled={features.desktop}
                    onOpenDesktop={openDesktop}
                    onLoadConversation={handleLoadConversation}
                    activeConversationId={activeConversationId}
                    onPanelToggle={handlePanelToggle}
                    customAppsEnabled={features.custom_apps}
                    homeAppEnabled={Boolean(homeAppSlug)}
                />

                {/* Main content area */}
                <div className={styles.mainContent}>
                    <FeatureSurfaces
                        view={view}
                        toolsRefreshSignal={toolsRefreshSignal}
                        composeInNewChat={composeInNewChat}
                        openArtifactInConversation={openArtifactInConversation}
                        customAppsEnabled={features.custom_apps}
                        customAppsCatalog={customAppsCatalog}
                        customApps={customApps}
                        homeAppSlug={homeAppSlug}
                    />
                    <MainSurface
                        view={view}
                        selectedAgentId={selectedAgentId}
                        hasPreview={hasPreview}
                        workspaceVisible={workspaceVisible}
                        workspaceSplit={workspaceSplit}
                        preview={preview}
                        browser={browser}
                        customApps={customApps}
                        agentState={agentState}
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
                            openPreview: openPreviewFromChat,
                            send: handleSend,
                            changeProfile: handleProfileChange,
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
