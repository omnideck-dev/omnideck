import { useCallback, useEffect, useState } from 'react';
import { useDesktopViewCommands, useVisibleViewIds } from '../desktop/DesktopViewRuntime.jsx';
import { useDesktopNavigationCommands } from '../navigation/DesktopNavigation.jsx';
import { CONVERSATION_VIEW_ID } from '../navigation/desktopNavigationViews.js';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import { useConversationSessionState } from '../conversation/session/ConversationSession.jsx';
import { label as conversationLabel } from '../../components/conversationSections.js';
import GoalDialog from './GoalDialog.jsx';
import GoalPanel from './GoalPanel.jsx';
import { useGoals } from './GoalsState.jsx';
import styles from './GoalPanel.module.css';

export const GOAL_VIEW_ID = 'goal';

/** The tab name: "Goal · " and the first few words of the chat's title. */
export function goalTabLabel(title) {
    const words = (title || '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join(' ');
    if (!words) return 'Goal';
    return `Goal · ${words.length > 24 ? `${words.slice(0, 23).trimEnd()}…` : words}`;
}

/** One Goal tab. It always shows the goal of the selected chat. */
export function goalDesktopView(label = 'Goal') {
    return {
        id: GOAL_VIEW_ID,
        type: 'goal',
        label,
        icon: 'bi-bullseye',
        identity: {},
        closable: true,
    };
}

export function useGoalDesktopActions() {
    const commands = useDesktopViewCommands();
    // Opening an open tab focuses it; the id never changes, so there is never a second Goal tab.
    const openGoal = useCallback(() => {
        commands.openView(goalDesktopView(), { tabGroupId: commands.preferredTabGroupId() });
    }, [commands]);
    return { openGoal };
}

export default function GoalDesktopView({ view }) {
    const { enabled } = useGoals();
    const { activeConversationId } = useConversationSessionState();
    if (!enabled) return <div className={styles.details}><p>The Goals experiment is turned off. Enable it in Settings to view this goal.</p></div>;
    if (!activeConversationId) return <div className={styles.details}><p className={styles.description}>Select a chat to see its goal.</p></div>;
    return <GoalConversationView key={activeConversationId} view={view} conversationId={activeConversationId} />;
}

function GoalConversationView({ view, conversationId }) {
    const [dialog, setDialog] = useState(null);
    const { isOffline } = useConversationSessionState();
    const { goalsByConversation } = useGoals();
    const { items } = useConversationCatalog();
    const navigation = useDesktopNavigationCommands();
    const commands = useDesktopViewCommands();
    const visibleIds = useVisibleViewIds();
    const goal = goalsByConversation[conversationId];
    const conversation = items.find((item) => item.conversation_id === conversationId);
    const tabLabel = goal ? goalTabLabel(conversation ? conversationLabel(conversation) : goal.objective) : 'Goal';

    useEffect(() => {
        if (view.label !== tabLabel) commands.updateViews([{ ...view, label: tabLabel }]);
    }, [commands, tabLabel, view]);

    const chatVisible = visibleIds.includes(CONVERSATION_VIEW_ID);
    return <>
        <GoalPanel conversationId={conversationId} isOffline={isOffline}
            onEdit={() => setDialog({ mode: 'edit' })}
            onStartGoal={() => setDialog({ mode: 'start' })}
            onOpenChat={chatVisible ? undefined : () => navigation.openConversation(conversationId)} />
        {dialog && <GoalDialog conversationId={conversationId} profileId={goal?.profile_id}
            onClose={() => setDialog(null)} />}
    </>;
}
