import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useRef,
    useState,
} from 'react';
import { useToast } from '../../../components/ToastProvider.jsx';
import { useConversationCatalog } from '../catalog/ConversationCatalog.jsx';
import { useAgentDispatch } from '../../agent/AgentState.jsx';
import useConversationSessionController from './useConversationSessionController.js';
import { useWorkspaceDispatch } from '../../workspace/WorkspaceState.jsx';
import { getConversationRestorePlan } from '../events/conversationRestore.js';
import { useAppEffectDispatch } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';

const ConversationSessionStateContext = createContext(null);
const ConversationSessionCommandsContext = createContext(null);

export function ConversationSessionProvider({ children }) {
    const agentDispatch = useAgentDispatch();
    const workspaceDispatch = useWorkspaceDispatch();
    const appEffectDispatch = useAppEffectDispatch();
    const { addStartedConversation } = useConversationCatalog();
    const { addToast } = useToast();
    const [conversationProfileId, setConversationProfileId] = useState(null);
    const isFreshConversationRef = useRef(true);

    const session = useConversationSessionController({
        agentDispatch,
        workspaceDispatch,
        appEffectDispatch,
    });

    const sendMessage = useCallback((message, attachments, profileId) => {
        if (!message && !attachments?.length) {
            return session.sendMessage(message, attachments, profileId);
        }
        if (isFreshConversationRef.current) {
            isFreshConversationRef.current = false;
            addStartedConversation({
                conversationId: session.activeConversationId,
                firstMessage: message || '',
            });
        }
        return session.sendMessage(message, attachments, profileId);
    }, [addStartedConversation, session.activeConversationId, session.sendMessage]);

    const sendNudge = useCallback(async (message, agentId) => {
        const result = await session.sendNudge(message, agentId);
        if (!result) return result;
        if (result.ok) {
            addToast('Nudge sent', { type: 'info', duration: 3000 });
        } else if (result.status === 409) {
            addToast('Agent is no longer running', { type: 'warn', duration: 5000 });
        } else {
            addToast(result.error || 'Could not send nudge', { type: 'error' });
        }
        return result;
    }, [addToast, session.sendNudge]);

    const loadConversation = useCallback(async (conversationId) => {
        const previousConversationId = session.activeConversationId;
        const loaded = await session.loadConversation(conversationId);
        if (!loaded) return false;

        if (
            previousConversationId
            && previousConversationId !== conversationId
        ) {
            appEffectDispatch({
                type: APP_EFFECT_TYPES.CLOSE_CONVERSATION_EXECUTION_VIEWS,
                conversationId: previousConversationId,
            });
        }
        const restore = getConversationRestorePlan(loaded);
        setConversationProfileId(loaded.profileId || null);
        agentDispatch({ type: 'RESET' });
        workspaceDispatch({ type: 'RESET' });
        for (const action of restore.agentActions) agentDispatch(action);
        for (const action of restore.workspaceActions) workspaceDispatch(action);
        isFreshConversationRef.current = false;
        return true;
    }, [
        agentDispatch,
        appEffectDispatch,
        session.activeConversationId,
        session.loadConversation,
        workspaceDispatch,
    ]);

    const newConversation = useCallback((options) => {
        if (session.activeConversationId) {
            appEffectDispatch({
                type: APP_EFFECT_TYPES.CLOSE_CONVERSATION_EXECUTION_VIEWS,
                conversationId: session.activeConversationId,
            });
        }
        const result = session.newConversation(options);
        isFreshConversationRef.current = true;
        setConversationProfileId(null);
        agentDispatch({ type: 'RESET' });
        workspaceDispatch({ type: 'RESET' });
        return result;
    }, [
        agentDispatch,
        appEffectDispatch,
        session.activeConversationId,
        session.newConversation,
        workspaceDispatch,
    ]);

    const state = useMemo(() => ({
        activeConversationId: session.activeConversationId,
        turns: session.turns,
        draft: session.draft,
        isStreaming: session.isStreaming,
        stopRequested: session.stopRequested,
        stalled: session.stalled,
        conversationProfileId,
    }), [
        conversationProfileId,
        session.activeConversationId,
        session.draft,
        session.isStreaming,
        session.stalled,
        session.stopRequested,
        session.turns,
    ]);

    const commands = useMemo(() => ({
        sendMessage,
        sendNudge,
        stopGeneration: session.stopGeneration,
        loadConversation,
        newConversation,
        setDraft: session.setDraft,
        setConversationProfileId,
    }), [
        loadConversation,
        newConversation,
        sendMessage,
        sendNudge,
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
