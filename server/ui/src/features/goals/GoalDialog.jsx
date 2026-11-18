import { useEffect, useRef } from 'react';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import GoalEditor from './GoalEditor.jsx';
import { isGoalOpen, useGoals } from './GoalsState.jsx';

export default function GoalDialog({ conversationId, profileId, initialObjective = '', onStarted, onClose }) {
    const { mutateGoal, goalsByConversation } = useGoals();
    const { refetch: refreshConversations } = useConversationCatalog();
    const mounted = useRef(true);
    const latest = goalsByConversation[conversationId];
    const goal = isGoalOpen(latest) ? latest : null;

    useEffect(() => {
        mounted.current = true;
        return () => { mounted.current = false; };
    }, []);

    const close = () => {
        if (mounted.current) onClose();
    };

    const save = async (body) => {
        await mutateGoal(conversationId, goal ? 'edit' : 'create', {
            ...body,
            ...(!goal ? { profile_id: profileId } : {}),
        });
        if (!goal) void refreshConversations();
        if (mounted.current) onStarted?.();
    };

    return <GoalEditor
        key={goal?.id || 'new'}
        goal={goal}
        latestGoal={latest}
        initialObjective={initialObjective}
        onSave={save}
        onClose={close}
    />;
}
