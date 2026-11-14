import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { isGoalOpen } from './goalStatus.js';

export const GOAL_POLL_MS = 3000;
const GoalsContext = createContext(null);

function newestGoal(current, incoming) {
    if (!current || !incoming) return incoming;
    if (current.id === incoming.id && current.revision > incoming.revision) return current;
    if (current.id !== incoming.id && Date.parse(current.created_at) > Date.parse(incoming.created_at)) return current;
    return incoming;
}

export { goalNeedsAnswer, goalStatus, isGoalOpen } from './goalStatus.js';

const DRAFT_PREFIX = 'omnideck_goal_answers:';

/** Answer drafts belong to one open goal. Drop drafts of ended goals and deleted chats. */
function pruneAnswerDrafts(goals) {
    try {
        const keep = new Set(goals.filter(isGoalOpen).map((goal) => `${DRAFT_PREFIX}${goal.conversation_id}:${goal.id}`));
        for (let index = localStorage.length - 1; index >= 0; index -= 1) {
            const key = localStorage.key(index);
            if (key?.startsWith(DRAFT_PREFIX) && !keep.has(key)) localStorage.removeItem(key);
        }
    } catch { /* Storage can be unavailable. */ }
}

/** Keep the previous object when no goal changed, so a poll does not re-render every consumer. */
function mergePolledGoals(current, goals) {
    const next = Object.fromEntries(goals.map((goal) => [goal.conversation_id, newestGoal(current[goal.conversation_id], goal)]));
    const keys = Object.keys(next);
    const unchanged = keys.length === Object.keys(current).length && keys.every((key) => {
        const before = current[key];
        const after = next[key];
        return before && before.id === after.id && before.revision === after.revision
            && before.running === after.running && before.run_id === after.run_id && before.last_run_id === after.last_run_id;
    });
    return unchanged ? current : next;
}

async function requestJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || 'Could not update the goal. Please try again.');
        error.status = response.status;
        throw error;
    }
    return data;
}

/** Keep goal status current even when its conversation is not open. */
export function GoalsProvider({ children, enabled = false }) {
    const [goalsByConversation, setGoals] = useState({});
    const [detailsByConversation, setDetails] = useState({});
    const [error, setError] = useState('');
    const [pollVersion, setPollVersion] = useState(0);
    const generation = useRef(0);
    const pollInFlight = useRef(false);
    const detailRequests = useRef({});

    const refresh = useCallback(async () => {
        if (!enabled || pollInFlight.current || navigator.onLine === false) return;
        pollInFlight.current = true;
        const startedGeneration = generation.current;
        try {
            const data = await requestJson('/api/goals');
            if (startedGeneration !== generation.current) return;
            setGoals((current) => mergePolledGoals(current, data.goals || []));
            pruneAnswerDrafts(data.goals || []);
            setPollVersion((current) => current + 1);
            setError('');
        } catch {
            setError('Goal status could not be refreshed. Reconnecting…');
        } finally {
            pollInFlight.current = false;
        }
    }, [enabled]);

    useEffect(() => {
        if (!enabled) return;
        let active = true;
        let timer;
        const poll = async () => {
            await refresh();
            if (active) timer = setTimeout(poll, GOAL_POLL_MS);
        };
        void poll();
        const onVisible = () => { if (!document.hidden) void refresh(); };
        window.addEventListener('online', refresh);
        document.addEventListener('visibilitychange', onVisible);
        return () => {
            active = false;
            generation.current += 1;
            clearTimeout(timer);
            window.removeEventListener('online', refresh);
            document.removeEventListener('visibilitychange', onVisible);
        };
    }, [enabled, refresh]);

    const acceptSnapshot = useCallback((conversationId, data) => {
        generation.current += 1;
        const goal = data.goal ? { ...data.goal, running: data.running ?? data.goal.running ?? false } : null;
        const snapshot = { ...data, goal };
        setDetails((current) => ({ ...current, [conversationId]: { ...snapshot, goal: newestGoal(current[conversationId]?.goal, goal) } }));
        setGoals((current) => {
            if (!goal) return current;
            return { ...current, [conversationId]: newestGoal(current[conversationId], goal) };
        });
        return snapshot;
    }, []);

    const loadGoal = useCallback(async (conversationId) => {
        const request = (detailRequests.current[conversationId] || 0) + 1;
        detailRequests.current[conversationId] = request;
        const data = await requestJson(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal`);
        if (detailRequests.current[conversationId] !== request) return data;
        return acceptSnapshot(conversationId, data);
    }, [acceptSnapshot]);

    const mutateGoal = useCallback(async (conversationId, action, body) => {
        generation.current += 1;
        detailRequests.current[conversationId] = (detailRequests.current[conversationId] || 0) + 1;
        const suffix = ['pause', 'resume', 'run', 'cancel', 'reopen'].includes(action) ? `/${action}` : '';
        try {
            const data = await requestJson(`/api/conversations/sessions/${encodeURIComponent(conversationId)}/goal${suffix}`, {
                method: action === 'edit' ? 'PATCH' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            return acceptSnapshot(conversationId, data);
        } catch (failure) {
            if (failure.status === 409) await loadGoal(conversationId).catch(() => {});
            throw failure;
        }
    }, [acceptSnapshot, loadGoal]);

    const value = useMemo(() => ({ enabled, goalsByConversation, detailsByConversation, error, pollVersion, refresh, loadGoal, mutateGoal }), [enabled, goalsByConversation, detailsByConversation, error, pollVersion, refresh, loadGoal, mutateGoal]);
    return <GoalsContext.Provider value={value}>{children}</GoalsContext.Provider>;
}

export function useGoals() {
    const context = useContext(GoalsContext);
    if (!context) throw new Error('useGoals must be used within GoalsProvider');
    return context;
}
