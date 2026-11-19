import { useCallback, useReducer } from 'react';

import { useAppEffectSubscription } from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import { activityReducer, initialActivityState } from './activityReducer.js';

export default function useConversationActivity() {
    const [activity, dispatch] = useReducer(activityReducer, initialActivityState);
    const onRuns = useCallback(/** @param {{ type: any, payload: { runs: import('../../app/appEffects.types').RunIdentity[] } }} effect */ (effect) => {
        dispatch({ type: effect.type, runs: effect.payload.runs });
    }, []);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_SNAPSHOT, onRuns);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_STARTED, onRuns);
    useAppEffectSubscription(APP_EFFECT_TYPES.RUNS_FINISHED, onRuns);
    const setVisibleConversation = useCallback(/** @param {string | null} conversationId */ (conversationId) => {
        dispatch({ type: 'visibility', conversationId });
    }, []);
    return { activity, setVisibleConversation };
}
