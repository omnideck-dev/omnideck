import { useCallback } from 'react';

import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import { useConversationSessionCommands } from '../conversation/session/ConversationSession.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
import { useGoalDesktopActions } from './GoalDesktopAdapter.jsx';
import GoalsView from './GoalsView.jsx';

export default function GoalsDesktopView() {
    const { newConversation } = useConversationSessionCommands();
    const { items, loading } = useConversationCatalog();
    const navigation = useDesktopNavigationCommands();
    const { openGoal } = useGoalDesktopActions();
    const openGoalChat = useCallback(async (conversationId) => {
        if (await navigation.openConversation(conversationId)) openGoal(conversationId);
    }, [navigation, openGoal]);
    const startGoal = useCallback(async (objective) => {
        const conversationId = await newConversation();
        navigation.openTarget({ kind: 'chat', conversationId, goalObjective: objective });
    }, [navigation, newConversation]);
    return <GoalsView conversations={items} loading={loading} onOpenGoal={openGoalChat} onStartGoal={startGoal} />;
}
