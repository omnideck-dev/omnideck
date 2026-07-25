import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import {
    useActiveConversationId,
    useConversationSessionCommands,
} from '../conversation/session/ConversationSession.jsx';

const DesktopNavigationStateContext = createContext(null);
const DesktopNavigationCommandsContext = createContext(null);

export function DesktopNavigationProvider({ children }) {
    const activeConversationId = useActiveConversationId();
    const { loadConversation } = useConversationSessionCommands();
    const [navigationTarget, setNavigationTarget] = useState(() => ({
        kind: 'chat',
        conversationId: activeConversationId || null,
    }));

    const open = useCallback((nextTarget) => {
        // Repeating a target is still a meaningful "open/select" request.
        // Its view may have been explicitly closed since the last request.
        setNavigationTarget(nextTarget);
    }, []);
    const openTarget = useCallback((nextTarget) => {
        open(nextTarget);
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
        openNetwork,
        openTarget,
        openRoutines,
        openSettings,
        openCustomApp,
    ]);
    const state = useMemo(
        () => ({ navigationTarget }),
        [navigationTarget],
    );

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
