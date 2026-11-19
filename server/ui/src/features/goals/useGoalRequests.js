import { useCallback, useEffect, useState } from 'react';

import { useConversationSessionState } from '../conversation/session/ConversationSession.jsx';
import { useGoalDesktopActions } from './GoalDesktopAdapter.jsx';
import { isGoalOpen, useGoals } from './GoalsState.jsx';

export default function useGoalRequests(conversationId) {
    const { enabled, goalsByConversation, startRequest, clearStartRequest } = useGoals();
    const { isOffline, stopRequested } = useConversationSessionState();
    const { openGoal } = useGoalDesktopActions();
    const [request, setRequest] = useState(null);

    useEffect(() => {
        setRequest((current) => (enabled && current?.conversationId === conversationId ? current : null));
    }, [conversationId, enabled]);

    useEffect(() => {
        if (!enabled || startRequest?.conversationId !== conversationId) return;
        setRequest({ conversationId, objective: startRequest.objective });
        clearStartRequest();
    }, [enabled, startRequest, conversationId, clearStartRequest]);

    const requestGoal = useCallback((next = {}) => {
        if (!enabled || isOffline || stopRequested) return;
        if (isGoalOpen(goalsByConversation[conversationId]) && !next.objective?.trim()) {
            openGoal(conversationId);
            next.onStarted?.();
            return;
        }
        setRequest({ ...next, conversationId });
    }, [enabled, isOffline, stopRequested, conversationId, goalsByConversation, openGoal]);

    const closeRequest = useCallback((closed) => {
        setRequest((current) => (current === closed ? null : current));
    }, []);

    return { request: request?.conversationId === conversationId ? request : null, requestGoal, closeRequest };
}
