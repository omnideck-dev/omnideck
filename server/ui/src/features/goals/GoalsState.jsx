import { createContext, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import { isGoalOpen } from './goalStatus.js';
import { DRAFT_PREFIX, draftKey } from './GoalQuestions.jsx';

const GoalsContext = createContext(null);

function newestGoal(current, incoming) {
    if (!current || !incoming) return incoming;
    if (current.id === incoming.id && current.revision > incoming.revision) return current;
    if (current.id !== incoming.id && Date.parse(current.created_at) > Date.parse(incoming.created_at)) return current;
    return incoming;
}

export { goalNeedsAnswer, goalStatus, isGoalOpen } from './goalStatus.js';

function pruneAnswerDrafts(goals) {
    try {
        const keep = new Set(goals.filter(isGoalOpen).map((goal) => draftKey(goal.conversation_id, goal.id)));
        for (let index = localStorage.length - 1; index >= 0; index -= 1) {
            const key = localStorage.key(index);
            if (key?.startsWith(DRAFT_PREFIX) && !keep.has(key)) localStorage.removeItem(key);
        }
    } catch { /* Storage can be unavailable. */ }
}

export async function requestJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || 'Could not update the goal. Please try again.');
        error.status = response.status;
        throw error;
    }
    return data;
}

export function GoalsProvider({ children, enabled = false }) {
    const [savedGoals, setGoals] = useState({});
    const [runs, setRuns] = useState({});
    const [detailsByConversation, setDetails] = useState({});
    const [startRequest, setStartRequest] = useState(null);
    const detailRequests = useRef({});

    const onGoalSnapshot = useCallback((effect) => {
        const goals = effect.payload.goals;
        setGoals(Object.fromEntries(goals.map((goal) => [goal.conversation_id, goal])));
        pruneAnswerDrafts(goals);
    }, []);
    const onGoalChanged = useCallback((effect) => {
        const { conversationId, goal } = effect.payload;
        setGoals((current) => ({ ...current, [conversationId]: newestGoal(current[conversationId], goal) }));
    }, []);
    const onRunSnapshot = useCallback((effect) => {
        setRuns(Object.fromEntries(effect.payload.runs.map((run) => [run.conversationId, run.runId])));
    }, []);
    const onRunStarted = useCallback((effect) => {
        setRuns((current) => ({ ...current, ...Object.fromEntries(effect.payload.runs.map((run) => [run.conversationId, run.runId])) }));
    }, []);
    const onRunFinished = useCallback((effect) => {
        setRuns((current) => {
            const next = { ...current };
            for (const run of effect.payload.runs) if (next[run.conversationId] === run.runId) delete next[run.conversationId];
            return next;
        });
    }, []);
    const onStartRequested = useCallback((effect) => setStartRequest(effect.payload), []);
    const clearStartRequest = useCallback(() => setStartRequest(null), []);
    useAppEffectSubscription(APP_EFFECT_TYPES.GOALS_START_REQUESTED, onStartRequested);
    useAppEffectSubscription(APP_EFFECT_TYPES.GOALS_SNAPSHOT, onGoalSnapshot);
    useAppEffectSubscription(APP_EFFECT_TYPES.GOALS_CHANGED, onGoalChanged);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_SNAPSHOT, onRunSnapshot);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_STARTED, onRunStarted);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_FINISHED, onRunFinished);

    const goalsByConversation = useMemo(() => {
        if (!enabled) return {};
        return Object.fromEntries(Object.entries(savedGoals).map(([conversationId, goal]) => [conversationId, {
            ...goal, running: Boolean(goal.last_run_id) && runs[conversationId] === goal.last_run_id,
        }]));
    }, [enabled, savedGoals, runs]);

    const acceptSnapshot = useCallback((conversationId, data) => {
        setDetails((current) => ({ ...current, [conversationId]: data }));
        if (data.goal) setGoals((current) => ({ ...current, [conversationId]: newestGoal(current[conversationId], data.goal) }));
        return data;
    }, []);

    const loadGoal = useCallback(async (conversationId) => {
        const request = (detailRequests.current[conversationId] || 0) + 1;
        detailRequests.current[conversationId] = request;
        const data = await requestJson(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal`);
        if (detailRequests.current[conversationId] !== request) return data;
        return acceptSnapshot(conversationId, data);
    }, [acceptSnapshot]);

    const mutateGoal = useCallback(async (conversationId, action, body) => {
        detailRequests.current[conversationId] = (detailRequests.current[conversationId] || 0) + 1;
        const suffix = ['pause', 'resume', 'run', 'cancel', 'reopen'].includes(action) ? `/${action}` : '';
        const data = await requestJson(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal${suffix}`, {
            method: action === 'edit' ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return acceptSnapshot(conversationId, data);
    }, [acceptSnapshot]);

    const value = useMemo(() => ({
        enabled, goalsByConversation, detailsByConversation, loadGoal, mutateGoal, startRequest, clearStartRequest,
    }), [enabled, goalsByConversation, detailsByConversation, loadGoal, mutateGoal, startRequest, clearStartRequest]);
    return <GoalsContext.Provider value={value}>{children}</GoalsContext.Provider>;
}

export function useGoals() {
    const context = useContext(GoalsContext);
    if (!context) throw new Error('useGoals must be used within GoalsProvider');
    return context;
}
