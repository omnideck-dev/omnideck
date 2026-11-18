import { useCallback, useEffect, useState } from 'react';
import { useAppData } from '../../contexts/AppData.jsx';
import { useDesktopViewCatalog, useDesktopViewCommands, useVisibleViewIds } from '../desktop/DesktopViewRuntime.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
import { CONVERSATION_VIEW_ID } from '../navigation/desktopNavigationViews.js';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import { useConversationSessionState, useSelectedProfileId } from '../conversation/session/ConversationSession.jsx';
import { label as conversationLabel } from '../../components/conversationSections.js';
import GoalDialog from './GoalDialog.jsx';
import GoalPanel from './GoalPanel.jsx';
import { GOAL_VIEW_ID, GOALS_VIEW_ID, goalDesktopView, goalTabLabel } from './goalDesktopViews.js';
import { useGoals } from './GoalsState.jsx';
import styles from './GoalPanel.module.css';

export function useGoalDesktopActions() {
    const commands = useDesktopViewCommands();
    const openGoal = useCallback(() => {
        commands.openView(goalDesktopView(), { tabGroupId: commands.preferredTabGroupId() });
    }, [commands]);
    return { openGoal };
}

/** Keeps the Goal tab's label on the selected chat, and closes goal tabs when Goals is turned off. */
export function GoalDesktopEffects() {
    const { features, featuresLoaded } = useAppData();
    const { enabled, goalsByConversation } = useGoals();
    const { activeConversationId } = useConversationSessionState();
    const { items } = useConversationCatalog();
    const catalog = useDesktopViewCatalog();
    const commands = useDesktopViewCommands();
    const goalView = catalog.openViews.find((view) => view.id === GOAL_VIEW_ID);
    const goal = goalsByConversation[activeConversationId];
    const conversation = items.find((item) => item.conversation_id === activeConversationId);
    const label = goal ? goalTabLabel(conversation ? conversationLabel(conversation) : goal.objective) : 'Goal';

    useEffect(() => {
        if (goalView && enabled && goalView.label !== label) commands.updateViews([{ ...goalView, label }]);
    }, [commands, goalView, enabled, label]);

    useEffect(() => {
        if (!featuresLoaded || features.goals) return;
        const ids = catalog.openViews.filter((view) => view.id === GOAL_VIEW_ID || view.id === GOALS_VIEW_ID).map((view) => view.id);
        if (ids.length) commands.closeViews(ids);
    }, [featuresLoaded, features.goals, catalog.openViews, commands]);
    return null;
}

export default function GoalDesktopView() {
    const { enabled } = useGoals();
    const { activeConversationId } = useConversationSessionState();
    if (!enabled) return null;
    if (!activeConversationId) return <div className={styles.details}><p className={styles.description}>Select a chat to see its goal.</p></div>;
    return <GoalConversationView key={activeConversationId} conversationId={activeConversationId} />;
}

function GoalConversationView({ conversationId }) {
    const [dialog, setDialog] = useState(null);
    const { isOffline } = useConversationSessionState();
    const selectedProfileId = useSelectedProfileId();
    const navigation = useDesktopNavigationCommands();
    const visibleIds = useVisibleViewIds();
    const chatVisible = visibleIds.includes(CONVERSATION_VIEW_ID);
    return <>
        <GoalPanel conversationId={conversationId} isOffline={isOffline}
            onEdit={() => setDialog({ mode: 'edit' })}
            onStartGoal={() => setDialog({ mode: 'start' })}
            onOpenChat={chatVisible ? undefined : () => navigation.openConversation(conversationId)} />
        {dialog && <GoalDialog conversationId={conversationId} profileId={selectedProfileId}
            onClose={() => setDialog(null)} />}
    </>;
}
