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
const ActiveConversationIdContext = createContext(undefined);
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
        if (session.isOffline) return null;
        if (isFreshConversationRef.current) {
            isFreshConversationRef.current = false;
            addStartedConversation({
                conversationId: session.activeConversationId,
                firstMessage: message || '',
            });
        }
        return session.sendMessage(message, attachments, profileId);
    }, [
        addStartedConversation,
        session.activeConversationId,
        session.isOffline,
        session.sendMessage,
    ]);

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
                type: APP_EFFECT_TYPES
                    .CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED,
                payload: { conversationId: previousConversationId },
            });
        }
        const restore = getConversationRestorePlan(loaded);
        setConversationProfileId(loaded.profileId || null);
        agentDispatch({ type: 'RESET' });
        workspaceDispatch({ type: 'RESET' });
        for (const action of restore.agentActions) agentDispatch(action);
        for (const action of restore.workspaceActions) workspaceDispatch(action);
        isFreshConversationRef.current = false;
        // Start replay only after the restored owners are ready. Otherwise a
        // fast live event could be delivered and immediately erased by RESET.
        if (loaded.activeRun) void session.reattachActiveRun(loaded);
        return true;
    }, [
        agentDispatch,
        appEffectDispatch,
        session.activeConversationId,
        session.loadConversation,
        session.reattachActiveRun,
        workspaceDispatch,
    ]);

    const newConversation = useCallback((options) => {
        if (session.activeConversationId) {
            appEffectDispatch({
                type: APP_EFFECT_TYPES
                    .CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED,
                payload: {
                    conversationId: session.activeConversationId,
                },
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

    /**
     * Append externally supplied material without exposing the composer's
     * storage or formatting rules to the source feature.
     */
    const composeFromSource = useCallback(({
        title = 'Source',
        text = '',
        context = null,
    }) => {
        let addition = text.trim();
        if (context !== null && context !== undefined) {
            try {
                const serialized = JSON.stringify(context, null, 2)
                    .slice(0, 12000);
                addition += `${addition ? '\n\n' : ''}`
                    + `Context from ${title}:\n${serialized}`;
            } catch {
                // Optional structured context must not discard authored text.
            }
        }
        if (!addition) return;
        session.setDraft((current) => (
            current.trim() ? `${current}\n\n${addition}` : addition
        ));
    }, [session.setDraft]);

    const state = useMemo(() => ({
        activeConversationId: session.activeConversationId,
        turns: session.turns,
        draft: session.draft,
        isStreaming: session.isStreaming,
        isOffline: session.isOffline,
        stopRequested: session.stopRequested,
        stalled: session.stalled,
        conversationProfileId,
    }), [
        conversationProfileId,
        session.activeConversationId,
        session.draft,
        session.isOffline,
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
        composeFromSource,
        setConversationProfileId,
    }), [
        composeFromSource,
        loadConversation,
        newConversation,
        sendMessage,
        sendNudge,
        session.setDraft,
        session.stopGeneration,
    ]);

    return (
        <ActiveConversationIdContext.Provider
            value={session.activeConversationId}
        >
            <ConversationSessionStateContext.Provider value={state}>
                <ConversationSessionCommandsContext.Provider value={commands}>
                    {children}
                </ConversationSessionCommandsContext.Provider>
            </ConversationSessionStateContext.Provider>
        </ActiveConversationIdContext.Provider>
    );
}

/** Subscribe to conversation identity without receiving streamed turn state. */
export function useActiveConversationId() {
    const activeConversationId = useContext(ActiveConversationIdContext);
    if (activeConversationId === undefined) {
        throw new Error(
            'useActiveConversationId must be used within ConversationSessionProvider',
        );
    }
    return activeConversationId;
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
