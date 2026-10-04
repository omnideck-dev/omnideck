import { useEffect, useRef } from 'react';
import { useGoals } from './GoalsState.jsx';
import { useConversationSessionCommands, useConversationSessionState } from '../conversation/session/ConversationSession.jsx';

/** Follow work that started while the user was viewing another part of the app. */
export default function GoalSessionBridge() {
    const { enabled, goalsByConversation, pollVersion } = useGoals();
    const { activeConversationId, isStreaming, isOffline } = useConversationSessionState();
    const { refreshActiveConversation } = useConversationSessionCommands();
    const goal = goalsByConversation[activeConversationId];
    const fingerprint = goal ? `${activeConversationId}:${goal.id}:${goal.revision}:${goal.run_id || ''}:${goal.last_run_id || ''}:${goal.running}` : null;
    const followed = useRef(null);
    useEffect(() => {
        if (!enabled || !fingerprint || isStreaming || isOffline || followed.current === fingerprint) return;
        let active = true;
        void refreshActiveConversation().then((refreshed) => {
            if (active && refreshed) followed.current = fingerprint;
        });
        return () => { active = false; };
    }, [enabled, fingerprint, isStreaming, isOffline, pollVersion, refreshActiveConversation]);
    return null;
}
