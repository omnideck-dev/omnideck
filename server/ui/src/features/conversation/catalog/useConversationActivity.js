import { useCallback, useEffect, useReducer } from 'react';

import { subscribeConversationActivity } from '../transport/conversationActivityClient.js';
import { activityReducer, initialActivityState } from './activityReducer.js';

export default function useConversationActivity() {
    const [activity, dispatch] = useReducer(activityReducer, initialActivityState);
    useEffect(() => subscribeConversationActivity(dispatch), []);
    const setVisibleConversation = useCallback(/** @param {string | null} conversationId */ (conversationId) => {
        dispatch({ type: 'visibility', conversationId });
    }, []);
    return { activity, setVisibleConversation };
}
