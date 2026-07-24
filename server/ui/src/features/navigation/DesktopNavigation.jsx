import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import {
    useConversationSessionCommands,
    useConversationSessionState,
} from '../conversation/session/ConversationSession.jsx';

const DesktopNavigationStateContext = createContext(null);
const DesktopNavigationCommandsContext = createContext(null);

export function DesktopNavigationProvider({ children }) {
    const { activeConversationId } = useConversationSessionState();
    const { loadConversation } = useConversationSessionCommands();
    const [destination, setDestination] = useState(() => ({
        kind: 'chat',
        conversationId: activeConversationId || null,
    }));

    const open = useCallback((nextDestination) => {
        // Repeating a destination is still a meaningful "open/select" request.
        // Its surface may have been explicitly closed since the last request.
        setDestination(nextDestination);
    }, []);
    const openDestination = useCallback((nextDestination) => {
        open(nextDestination);
    }, [open]);

    const openChat = useCallback((conversationId = activeConversationId) => {
        open({ kind: 'chat', conversationId: conversationId || null });
    }, [activeConversationId, open]);
    const openNetwork = useCallback((agentId = null) => {
        open({ kind: 'network', conversationId: activeConversationId || null, agentId });
    }, [activeConversationId, open]);
    const openAgent = useCallback((agentId) => openNetwork(agentId), [openNetwork]);
    const openSettings = useCallback((tab = null) => open({ kind: 'settings', tab }), [open]);
    const openAgents = useCallback((profileId = null) => open({ kind: 'agents', profileId }), [open]);
    const openRoutines = useCallback(
        (routineId = null, runId = null) => open({ kind: 'routines', routineId, runId }),
        [open],
    );
    const openArtifacts = useCallback(
        (conversationId = null) => open({ kind: 'artifacts', conversationId }),
        [open],
    );
    const openApps = useCallback(() => open({ kind: 'apps' }), [open]);
    const openCustomApp = useCallback(
        (appSlug) => open({ kind: 'custom-app', appSlug }),
        [open],
    );

    const openConversation = useCallback(async (conversationId, { artifactId = null } = {}) => {
        if (conversationId !== activeConversationId) {
            const loaded = await loadConversation(conversationId);
            if (!loaded) return false;
        }
        open({
            kind: 'chat',
            conversationId,
            ...(artifactId ? { artifactId } : {}),
        });
        return true;
    }, [activeConversationId, loadConversation, open]);

    const commands = useMemo(() => ({
        openDestination,
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
        openNetwork,
        openDestination,
        openRoutines,
        openSettings,
        openCustomApp,
    ]);
    const state = useMemo(() => ({ destination }), [destination]);

    return (
        <DesktopNavigationStateContext.Provider value={state}>
            <DesktopNavigationCommandsContext.Provider value={commands}>
                {children}
            </DesktopNavigationCommandsContext.Provider>
        </DesktopNavigationStateContext.Provider>
    );
}

export function useDesktopNavigationState() {
    const state = useContext(DesktopNavigationStateContext);
    if (state === null) {
        throw new Error('useDesktopNavigationState must be used within DesktopNavigationProvider');
    }
    return state;
}

export function useDesktopNavigationCommands() {
    const commands = useContext(DesktopNavigationCommandsContext);
    if (commands === null) {
        throw new Error('useDesktopNavigationCommands must be used within DesktopNavigationProvider');
    }
    return commands;
}

export function useDesktopNavigation() {
    return {
        ...useDesktopNavigationState(),
        ...useDesktopNavigationCommands(),
    };
}
