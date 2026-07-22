import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useState,
} from 'react';
import { useToast } from '../../../components/ToastProvider.jsx';
import { useConversationCatalog } from '../catalog/ConversationCatalog.jsx';
import { useAgentDispatch } from '../../agent/AgentState.jsx';
import useConversationSessionController from './useConversationSessionController.js';
import { useWorkspaceDispatch } from '../../workspace/WorkspaceState.jsx';
import { getConversationRestorePlan } from '../events/conversationRestore.js';
import { useCustomToolsCatalog } from '../../customTools/CustomToolsCatalog.jsx';

const ConversationSessionStateContext = createContext(null);
const ConversationSessionCommandsContext = createContext(null);

export function ConversationSessionProvider({ children }) {
    const agentDispatch = useAgentDispatch();
    const workspaceDispatch = useWorkspaceDispatch();
    const { addStartedConversation } = useConversationCatalog();
    const { refreshCustomTools } = useCustomToolsCatalog();
    const { addToast } = useToast();
    const [conversationProfileId, setConversationProfileId] = useState(null);
    const [pendingAudio, setPendingAudio] = useState(null);

    const callbacks = useMemo(() => ({
        onAgentAction: agentDispatch,
        onWorkspaceAction: workspaceDispatch,
        onToolCreated: refreshCustomTools,
        onAudioPlayback: setPendingAudio,
        onNudgeSent: (result) => {
            if (result.ok) {
                addToast('Nudge sent', { type: 'info', duration: 3000 });
            } else if (result.status === 409) {
                addToast('Agent is no longer running', { type: 'warn', duration: 5000 });
            } else {
                addToast(result.error || 'Could not send nudge', { type: 'error' });
            }
        },
        onConversationLoaded: ({ events, browserTabs, terminal, previewState, profileId }) => {
            const restore = getConversationRestorePlan({
                events,
                browserTabs,
                terminal,
                previewState,
            });
            setConversationProfileId(profileId || null);
            agentDispatch({ type: 'RESET' });
            workspaceDispatch({ type: 'RESET' });
            for (const action of restore.agentActions) agentDispatch(action);
            for (const action of restore.workspaceActions) workspaceDispatch(action);
            workspaceDispatch({ type: 'RESTORE_ACTIVE_TAB', activeTab: restore.activeTab });
        },
        onConversationStarted: addStartedConversation,
    }), [addStartedConversation, addToast, agentDispatch, refreshCustomTools, workspaceDispatch]);

    const session = useConversationSessionController(callbacks);

    const newConversation = useCallback((options) => {
        const result = session.newConversation(options);
        setConversationProfileId(null);
        agentDispatch({ type: 'RESET' });
        workspaceDispatch({ type: 'RESET' });
        return result;
    }, [agentDispatch, session.newConversation, workspaceDispatch]);

    const clearPendingAudio = useCallback(() => setPendingAudio(null), []);

    const state = useMemo(() => ({
        activeConversationId: session.activeConversationId,
        turns: session.turns,
        draft: session.draft,
        isStreaming: session.isStreaming,
        stopRequested: session.stopRequested,
        stalled: session.stalled,
        conversationProfileId,
        pendingAudio,
    }), [
        conversationProfileId,
        pendingAudio,
        session.activeConversationId,
        session.draft,
        session.isStreaming,
        session.stalled,
        session.stopRequested,
        session.turns,
    ]);

    const commands = useMemo(() => ({
        sendMessage: session.sendMessage,
        sendNudge: session.sendNudge,
        stopGeneration: session.stopGeneration,
        loadConversation: session.loadConversation,
        newConversation,
        setDraft: session.setDraft,
        savePreviewState: session.savePreviewState,
        setConversationProfileId,
        clearPendingAudio,
    }), [
        clearPendingAudio,
        newConversation,
        session.loadConversation,
        session.savePreviewState,
        session.sendMessage,
        session.sendNudge,
        session.setDraft,
        session.stopGeneration,
    ]);

    return (
        <ConversationSessionStateContext.Provider value={state}>
            <ConversationSessionCommandsContext.Provider value={commands}>
                {children}
            </ConversationSessionCommandsContext.Provider>
        </ConversationSessionStateContext.Provider>
    );
}

export function useConversationSessionState() {
    const state = useContext(ConversationSessionStateContext);
    if (state === null) {
        throw new Error('useConversationSessionState must be used within ConversationSessionProvider');
    }
    return state;
}

export function useConversationSessionCommands() {
    const commands = useContext(ConversationSessionCommandsContext);
    if (commands === null) {
        throw new Error('useConversationSessionCommands must be used within ConversationSessionProvider');
    }
    return commands;
}

export function useConversationSession() {
    return {
        ...useConversationSessionState(),
        ...useConversationSessionCommands(),
    };
}
