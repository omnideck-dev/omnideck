import { useEffect } from 'react';
import { act } from '@testing-library/react';

import { AppEffectsProvider, useAppEffectDispatch } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import { GoalsProvider } from '../GoalsState.jsx';

let dispatchEffect = null;

function withRun(goal) {
    return goal.running && !goal.last_run_id ? { ...goal, last_run_id: 'run-test' } : goal;
}

function runsOf(goals) {
    return goals.filter((goal) => goal.running).map((goal) => ({ conversationId: goal.conversation_id, runId: withRun(goal).last_run_id }));
}

function Seed({ goals, children }) {
    const dispatch = useAppEffectDispatch();
    useEffect(() => {
        dispatchEffect = dispatch;
        dispatch({ type: APP_EFFECT_TYPES.RUNS_SNAPSHOT, payload: { runs: runsOf(goals) } });
        dispatch({ type: APP_EFFECT_TYPES.GOALS_SNAPSHOT, payload: { goals: goals.map(withRun) } });
        return () => { dispatchEffect = null; };
    }, []);
    return children;
}

/** Goals state fed through the activity effects, as the activity stream feeds it. */
export function GoalsTestProvider({ goals = [], enabled = true, children }) {
    return <AppEffectsProvider>
        <Seed goals={goals}>
            <GoalsProvider enabled={enabled}>{children}</GoalsProvider>
        </Seed>
    </AppEffectsProvider>;
}

/** Send a saved goal, and its run state, the way the activity stream does. */
export function emitGoal(goal) {
    const saved = withRun(goal);
    act(() => {
        dispatchEffect({ type: APP_EFFECT_TYPES.GOALS_CHANGED, payload: { conversationId: goal.conversation_id, goal: saved } });
        if (goal.running) dispatchEffect({ type: APP_EFFECT_TYPES.RUNS_STARTED, payload: { runs: runsOf([goal]) } });
        else if (saved.last_run_id) dispatchEffect({ type: APP_EFFECT_TYPES.RUNS_FINISHED, payload: { runs: [{ conversationId: goal.conversation_id, runId: saved.last_run_id }] } });
    });
}

export function emitEffect(type, payload) {
    act(() => dispatchEffect({ type, payload }));
}
