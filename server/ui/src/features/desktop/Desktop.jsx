import {
    useCallback,
    useEffect,
    useMemo,
    useRef,
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
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../navigation/DesktopNavigation.jsx';
import useConversationExecutionView from '../workspace/useConversationExecutionView.js';
import DesktopSurfaceContent from './DesktopSurfaceContent.jsx';
import DesktopWindowLayout from './DesktopWindowLayout.jsx';
import GlobalOverlays from './GlobalOverlays.jsx';
import { createDesktopSurfaceActions } from './desktopSurfaceActions.js';
import {
    loadDesktopWindowSnapshot,
    saveDesktopWindowSnapshot,
} from './desktopWindowPersistence.js';
import useConversationExecutionSurfaces from './useConversationExecutionSurfaces.js';
import useCustomAppSurfaceController from './useCustomAppSurfaceController.js';
import useDesktopWindowManager, {
    DESKTOP_PANE_IDS,
} from './useDesktopWindowManager.jsx';
import {
    createArtifactSurface,
    createDestinationSurface,
    createFileOutputSurface,
} from './desktopSurfaces.js';
import styles from '../../App.module.css';

const INITIAL_CHAT_SURFACE = createDestinationSurface({
    kind: 'chat',
    conversationId: null,
});

function fallbackSurface(model, paneId, closingSurfaceId) {
    const pane = model.panes[paneId];
    const index = pane.surfaceIds.indexOf(closingSurfaceId);
    const remainingIds = pane.surfaceIds.filter((id) => id !== closingSurfaceId);
    const fallbackId = remainingIds[index] || remainingIds[index - 1] || null;
    return fallbackId ? model.surfacesById[fallbackId] : null;
}

function activeExecutionSurface(model) {
    const focusedFloatingSurface = model.focusedFloatingSurfaceId
        ? model.surfacesById[model.focusedFloatingSurfaceId]
        : null;
    if (focusedFloatingSurface?.kind === 'conversation-execution') {
        return focusedFloatingSurface;
    }

    const focusedPane = model.focusedPaneId
        ? model.panes[model.focusedPaneId]
        : null;
    const focusedSurface = focusedPane?.activeSurfaceId
        ? model.surfacesById[focusedPane.activeSurfaceId]
        : null;
    if (focusedSurface?.kind === 'conversation-execution') return focusedSurface;

    for (const paneId of [DESKTOP_PANE_IDS.RIGHT, DESKTOP_PANE_IDS.LEFT]) {
        const surfaceId = model.panes[paneId].activeSurfaceId;
        const surface = model.surfacesById[surfaceId];
        if (surface?.kind === 'conversation-execution') {
            return surface;
        }
    }
    return null;
}

function surfaceForDestination(windowState, destination) {
    if (!destination) return null;
    if (destination.kind === 'custom-app') {
        return windowState.surfacesById[`custom-app:${destination.appSlug}`] || null;
    }
    const surface = createDestinationSurface(destination);
    return surface ? windowState.surfacesById[surface.id] || null : null;
}

function restoredNavigationDestination(snapshot) {
    if (!snapshot) return null;
    const { windowState, navigationDestination } = snapshot;
    if (surfaceForDestination(windowState, navigationDestination)) {
        return navigationDestination;
    }

    const paneOrder = [
        windowState.focusedPaneId,
        DESKTOP_PANE_IDS.LEFT,
        DESKTOP_PANE_IDS.RIGHT,
    ].filter((paneId, index, all) => paneId && all.indexOf(paneId) === index);
    for (const paneId of paneOrder) {
        const activeSurfaceId = windowState.panes[paneId].activeSurfaceId;
        const activeSurface = windowState.surfacesById[activeSurfaceId];
        if (activeSurface?.destination) return activeSurface.destination;
    }
    return windowState.surfacesById['destination:conversation']?.destination || null;
}

/** Composes feature-owned renderers into two generic desktop pane stacks. */
export default function Desktop() {
    const { destination } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const { profilesHook, features } = useAppData();
    const { defaultProfileId } = useAppSettings();
    const customApps = useCustomApps();
    const { addToast } = useToast();
    const [userDesktopOpen, setUserDesktopOpen] = useState(false);

    const {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        sendMessage,
        sendNudge,
        stopGeneration,
        loadConversation,
        newConversation: startNewConversation,
        activeConversationId,
        draft,
        setDraft,
        conversationProfileId,
        setConversationProfileId,
    } = useConversationSession();

    const [desktopRestore] = useState(loadDesktopWindowSnapshot);
    const [restorationReady, setRestorationReady] = useState(!desktopRestore);
    const restoreStartedRef = useRef(false);
    const preserveRestoredSelectionRef = useRef(Boolean(desktopRestore));
    const windowManager = useDesktopWindowManager({
        initialSurface: INITIAL_CHAT_SURFACE,
        initialWindowState: desktopRestore?.windowState || null,
    });
    const executionSurfaces = useConversationExecutionSurfaces({
        activeConversationId,
        windowManager,
    });
    const {
        closeConversationViews,
        closeExecutionSurface,
        openAgentView,
        preferredPaneId,
    } = executionSurfaces;
    const executionActiveSurface = activeExecutionSurface(windowManager.model);
    const selectedAgentId = destination.kind === 'network'
        ? destination.agentId
        : null;
    const { browser } = useConversationExecutionView({
        conversationId: activeConversationId,
        isStreaming,
        activeSurface: executionActiveSurface,
    });

    const destinationSurface = useMemo(
        () => createDestinationSurface(destination),
        [destination],
    );

    useEffect(() => {
        if (!desktopRestore || restoreStartedRef.current) return undefined;
        restoreStartedRef.current = true;
        let cancelled = false;

        const restoreDesktop = async () => {
            const conversationSurface = desktopRestore.windowState
                .surfacesById['destination:conversation'];
            const conversationId = conversationSurface?.destination?.conversationId;
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

            let nextDestination = restoredNavigationDestination(desktopRestore);
            if (!conversationLoaded) {
                windowManager.commands.reconcileSurfaceGroup(
                    'conversation-execution',
                    [],
                );
                nextDestination = {
                    kind: 'chat',
                    conversationId: activeConversationId,
                };
            }
            if (nextDestination) {
                navigation.openDestination(nextDestination);
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
                !destinationSurface
                || !windowManager.model.surfacesById[destinationSurface.id]
            ) {
                return;
            }
            windowManager.commands.openSurface(
                destinationSurface,
                DESKTOP_PANE_IDS.LEFT,
                { activate: false },
            );
            return;
        }
        if (!destinationSurface) return;
        windowManager.commands.openSurface(
            destinationSurface,
            DESKTOP_PANE_IDS.LEFT,
        );
    }, [
        destinationSurface,
        restorationReady,
        windowManager.commands.openSurface,
    ]);

    useEffect(() => {
        if (!restorationReady) return;
        saveDesktopWindowSnapshot(windowManager.model, destination);
    }, [
        destination,
        restorationReady,
        windowManager.model,
    ]);

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

    const customAppSurfaces = useCustomAppSurfaceController({
        customApps,
        destination,
        windowManager,
        navigation,
        setDraft,
    });

    const newConversation = useCallback(async (options) => {
        const conversationId = await startNewConversation(options);
        navigation.openChat(conversationId);
        return conversationId;
    }, [navigation, startNewConversation]);

    const composeInNewConversation = useCallback(
        (text) => newConversation({ draft: text }),
        [newConversation],
    );

    const handleLoadConversation = useCallback(async (conversationId) => (
        navigation.openConversation(conversationId)
    ), [navigation]);

    const handleArtifactError = useCallback(() => {
        addToast('Could not open the artifact', { type: 'error' });
    }, [addToast]);
    const openArtifact = useCallback((artifact, paneId = null) => {
        const surface = createArtifactSurface(artifact);
        if (!surface) return;
        windowManager.commands.openSurface(
            surface,
            paneId || preferredPaneId(),
        );
    }, [
        preferredPaneId,
        windowManager.commands.openSurface,
    ]);
    const openFileOutput = useCallback((item) => {
        const surface = createFileOutputSurface(item, activeConversationId);
        if (!surface) return;
        windowManager.commands.openSurface(
            surface,
            preferredPaneId(),
        );
    }, [
        activeConversationId,
        preferredPaneId,
        windowManager.commands.openSurface,
    ]);
    const openArtifactInConversation = useArtifactNavigation({
        destination,
        navigation,
        openArtifact,
        onError: handleArtifactError,
    });
    const openConversationArtifacts = useCallback((conversationId, paneId) => {
        const surface = createDestinationSurface({
            kind: 'artifacts',
            conversationId,
        });
        windowManager.commands.openSurface(
            surface,
            paneId || preferredPaneId(),
        );
        navigation.openDestination(surface.destination);
    }, [
        navigation,
        preferredPaneId,
        windowManager.commands.openSurface,
    ]);

    const agentCounts = useAgentNetworkCounts();
    const handleOpenNetwork = useCallback(() => navigation.openNetwork(), [navigation]);
    const handleCloseNetwork = useCallback(() => navigation.openChat(), [navigation]);
    const handleSelectAgent = useCallback((agentId) => navigation.openAgent(agentId), [navigation]);

    const handleSelectSurface = useCallback((paneId, surfaceId) => {
        windowManager.commands.selectSurface(paneId, surfaceId);
        const surface = windowManager.model.surfacesById[surfaceId];
        if (surface?.destination) {
            navigation.openDestination(surface.destination);
        }
    }, [
        navigation,
        windowManager.commands.selectSurface,
        windowManager.model.surfacesById,
    ]);

    const closeManagedSurface = useCallback((surface) => {
        if (surface.kind === 'conversation-execution') {
            closeExecutionSurface(surface);
        } else {
            if (surface.kind === 'conversation') {
                closeConversationViews(surface.destination?.conversationId);
            }
            windowManager.commands.closeSurface(surface.id);
        }
    }, [
        closeConversationViews,
        closeExecutionSurface,
        windowManager.commands.closeSurface,
    ]);

    const handleCloseSurface = useCallback((paneId, surfaceId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (!surface) return;
        const wasActive = Boolean(
            paneId
            && windowManager.model.panes[paneId]?.activeSurfaceId === surfaceId,
        );
        const fallback = wasActive
            ? fallbackSurface(windowManager.model, paneId, surfaceId)
            : null;
        const floatingFallback = !paneId && surface.destination
            ? [
                ...windowManager.model.floatingWindows
                    .filter((window) => window.surfaceId !== surfaceId)
                    .sort((left, right) => right.zIndex - left.zIndex)
                    .map((window) => (
                        windowManager.model.surfacesById[window.surfaceId]
                    )),
                ...[
                    windowManager.model.focusedPaneId,
                    DESKTOP_PANE_IDS.LEFT,
                    DESKTOP_PANE_IDS.RIGHT,
                ]
                    .filter((candidate, index, all) => (
                        candidate && all.indexOf(candidate) === index
                    ))
                    .map((candidate) => {
                        const activeSurfaceId = windowManager.model
                            .panes[candidate].activeSurfaceId;
                        return windowManager.model.surfacesById[activeSurfaceId];
                    }),
            ].find((candidate) => candidate?.destination)
            : null;

        closeManagedSurface(surface);

        if (wasActive) {
            if (fallback?.destination) navigation.openDestination(fallback.destination);
        } else if (floatingFallback?.destination) {
            navigation.openDestination(floatingFallback.destination);
        }
    }, [
        closeManagedSurface,
        navigation,
        windowManager.model,
    ]);

    const handleMoveSurface = useCallback((surfaceId, targetPaneId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (!surface) return;

        windowManager.commands.moveSurface(surfaceId, targetPaneId);
        if (surface.destination) {
            navigation.openDestination(surface.destination);
        }
    }, [
        navigation,
        windowManager.commands.moveSurface,
        windowManager.model,
    ]);

    const handleFloatSurface = useCallback((surfaceId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (!surface) return;
        windowManager.commands.floatSurface(surfaceId);
        if (surface.destination) {
            navigation.openDestination(surface.destination);
        }
    }, [
        navigation,
        windowManager.commands.floatSurface,
        windowManager.model.surfacesById,
    ]);

    const handleFocusSurface = useCallback((surfaceId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (surface?.destination) {
            navigation.openDestination(surface.destination);
        }
    }, [
        navigation,
        windowManager.model.surfacesById,
    ]);

    const handleEnterFullscreen = useCallback((surfaceId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (!surface) return;
        windowManager.commands.enterFullscreen(surfaceId);
        if (surface.destination) {
            navigation.openDestination(surface.destination);
        }
    }, [
        navigation,
        windowManager.commands.enterFullscreen,
        windowManager.model.surfacesById,
    ]);

    const closeSurfaceBatch = useCallback((
        paneId,
        surfaceIds,
        activateSurfaceId = null,
    ) => {
        const uniqueIds = [...new Set(surfaceIds)];
        const surfaces = uniqueIds
            .map((surfaceId) => windowManager.model.surfacesById[surfaceId])
            .filter((surface) => surface && surface.closable !== false)
            // Let a closing Conversation clear execution-view dismissal state
            // after its individual execution surfaces have closed.
            .sort((left, right) => (
                Number(left.kind === 'conversation')
                - Number(right.kind === 'conversation')
            ));
        for (const surface of surfaces) closeManagedSurface(surface);

        const activatedSurface = activateSurfaceId
            ? windowManager.model.surfacesById[activateSurfaceId]
            : null;
        if (activatedSurface) {
            windowManager.commands.selectSurface(paneId, activateSurfaceId);
            if (activatedSurface.destination) {
                navigation.openDestination(activatedSurface.destination);
            }
        }
    }, [
        closeManagedSurface,
        navigation,
        windowManager.commands.selectSurface,
        windowManager.model.surfacesById,
    ]);

    const handleCloseOtherSurfaces = useCallback((paneId, keepSurfaceId) => {
        const pane = windowManager.model.panes[paneId];
        const surfaceIds = pane.surfaceIds.filter(
            (surfaceId) => (
                surfaceId !== keepSurfaceId
                && windowManager.model.surfacesById[surfaceId]?.closable !== false
            ),
        );
        closeSurfaceBatch(paneId, surfaceIds, keepSurfaceId);
    }, [
        closeSurfaceBatch,
        windowManager.model.panes,
        windowManager.model.surfacesById,
    ]);

    const handleCloseSurfacesToRight = useCallback((paneId, surfaceId) => {
        const pane = windowManager.model.panes[paneId];
        const surfaceIndex = pane.surfaceIds.indexOf(surfaceId);
        if (surfaceIndex < 0) return;
        const surfaceIds = pane.surfaceIds
            .slice(surfaceIndex + 1)
            .filter(
                (candidateId) => (
                    windowManager.model.surfacesById[candidateId]?.closable !== false
                ),
            );
        const activateSurfaceId = surfaceIds.includes(pane.activeSurfaceId)
            ? surfaceId
            : null;
        closeSurfaceBatch(paneId, surfaceIds, activateSurfaceId);
    }, [
        closeSurfaceBatch,
        windowManager.model.panes,
        windowManager.model.surfacesById,
    ]);

    const surfaceActionCommands = useMemo(() => ({
        moveSurface: handleMoveSurface,
        floatSurface: handleFloatSurface,
        enterFullscreen: handleEnterFullscreen,
        reloadCustomApp: customAppSurfaces.reloadApp,
        openArtifactConversation: openArtifactInConversation,
        closeSurface: handleCloseSurface,
        closeOtherSurfaces: handleCloseOtherSurfaces,
        closeSurfacesToRight: handleCloseSurfacesToRight,
    }), [
        customAppSurfaces.reloadApp,
        handleFloatSurface,
        handleCloseOtherSurfaces,
        handleCloseSurface,
        handleCloseSurfacesToRight,
        handleEnterFullscreen,
        handleMoveSurface,
        openArtifactInConversation,
    ]);
    const getSurfaceActions = useCallback((surface, paneId, options = {}) => (
        createDesktopSurfaceActions({
            surface,
            paneId,
            pane: paneId ? windowManager.model.panes[paneId] : null,
            floating: options.floating,
            commands: surfaceActionCommands,
        })
    ), [
        surfaceActionCommands,
        windowManager.model.panes,
    ]);

    const mainActions = {
        closeNetwork: handleCloseNetwork,
        openNetwork: handleOpenNetwork,
        selectAgent: handleSelectAgent,
        openPreview: openFileOutput,
        openExecutionView: openAgentView,
        openArtifacts: openConversationArtifacts,
        send: handleSend,
        changeProfile: handleProfileChange,
    };
    const pageActions = {
        composeInNewConversation,
        openArtifactInConversation,
        openArtifact,
        openApp: customAppSurfaces.openApp,
    };
    const customAppActions = {
        openChat: customAppSurfaces.openChatFromApp,
        composeInChat: customAppSurfaces.composeFromApp,
    };
    const session = {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        sendNudge,
        stopGeneration,
        activeConversationId,
        draft,
        setDraft,
    };

    return (
        <div className={styles.desktop}>
            <div className={styles.bodyRow}>
                <Sidebar
                    onNewConversation={newConversation}
                    desktopEnabled={features.desktop}
                    onOpenDesktop={openDesktop}
                    onLoadConversation={handleLoadConversation}
                    activeConversationId={activeConversationId}
                />

                <div className={styles.mainContent}>
                    <DesktopWindowLayout
                        model={windowManager.model}
                        commands={windowManager.commands}
                        onSelectSurface={handleSelectSurface}
                        onFocusSurface={handleFocusSurface}
                        onCloseSurface={handleCloseSurface}
                        getSurfaceActions={getSurfaceActions}
                        renderSurface={(surface, { active, paneId }) => (
                            <DesktopSurfaceContent
                                surface={surface}
                                active={active}
                                paneId={paneId}
                                workspace={{ browser }}
                                agentCounts={agentCounts}
                                session={session}
                                selectedProfileId={selectedProfileId}
                                profileRevision={profilesHook.revision}
                                actions={{
                                    main: mainActions,
                                    pages: pageActions,
                                    customApp: customAppActions,
                                }}
                            />
                        )}
                    />
                </div>
            </div>

            <GlobalOverlays
                userDesktopOpen={userDesktopOpen}
                closeUserDesktop={() => setUserDesktopOpen(false)}
            />
        </div>
    );
}
