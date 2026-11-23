import { useGoals } from '../goals/GoalsState.jsx';
import { useCallback } from 'react';

import ChatPanel from '../../components/ChatPanel.jsx';
import { label as conversationLabel } from '../../components/conversationSections.js';
import { useConversationCatalog } from './catalog/ConversationCatalog.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import AgentNetworkView from '../agent/AgentNetworkView.jsx';
import useAgentNetworkCounts from '../agent/useAgentNetworkCounts.js';
import {
    useArtifactDesktopActions,
} from '../artifacts/ArtifactDesktopAdapter.jsx';
import {
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import {
    navigationTargetForView,
} from '../navigation/desktopNavigationViews.js';
import {
    useWorkspaceResourceDesktopActions,
} from '../workspace/WorkspaceResourceDesktopAdapter.jsx';
import {
    useConversationSessionCommands,
    useConversationSessionState,
    useSelectedProfileId,
} from './session/ConversationSession.jsx';
import styles from '../../App.module.css';
import { useGoalDesktopActions } from '../goals/GoalDesktopAdapter.jsx';
import GoalRequestDialog from '../goals/GoalRequestDialog.jsx';
import useGoalRequests from '../goals/useGoalRequests.js';

/** Conversation-domain adapter for Chat and Agent Network modes. */
export default function ConversationDesktopView({ view, tabGroupId }) {
    const {
        activeConversationId,
        turns,
        draft,
        isOffline,
        stopRequested,
        stalled,
        isStreaming,
        queue,
        returned,
    } = useConversationSessionState();
    const {
        sendMessage,
        sendAnswers,
        removeQueuedMessage,
        consumeReturnedMessages,
        sendNudge,
        stopGeneration,
        setDraft,
        pickConversationProfile,
    } = useConversationSessionCommands();
    const { profilesHook, features } = useAppData();
    const { goalsByConversation } = useGoals();
    const { openGoal } = useGoalDesktopActions();
    const navigation = useDesktopNavigationCommands();
    const agentCounts = useAgentNetworkCounts();
    const artifacts = useArtifactDesktopActions();
    const {
        openAgentWorkspaceResource,
    } = useWorkspaceResourceDesktopActions();

    const selectedProfileId = useSelectedProfileId();
    const { items: catalogItems, addConversation } = useConversationCatalog();
    const listed = catalogItems.find((item) => item.conversation_id === activeConversationId);
    const chatTitle = listed ? conversationLabel(listed) : 'New chat';
    const navigationTarget = navigationTargetForView(view);
    const mode = navigationTarget?.kind || 'chat';
    const selectedAgentId = navigationTarget?.agentId || null;
    const { request: goalRequest, requestGoal, closeRequest } = useGoalRequests(activeConversationId);

    const handleSend = useCallback((message, attachments) => (
        sendMessage(message, attachments, selectedProfileId)
    ), [selectedProfileId, sendMessage]);

    const handleSendAnswers = useCallback(async (goalId, answers) => {
        const result = await sendAnswers(goalId, answers, selectedProfileId);
        if (result && !result.ok) throw new Error(result.error || 'Your answers were not sent.');
        return { queued: Boolean(result?.queued) };
    }, [selectedProfileId, sendAnswers]);

    if (mode === 'network') {
        return (
            <div className={selectedAgentId ? styles.chatColumn : styles.networkArea}>
                <AgentNetworkView
                    selectedAgentId={selectedAgentId}
                    turns={turns}
                    agentCounts={agentCounts}
                    onClose={() => navigation.openChat()}
                    onOpenOverview={() => navigation.openNetwork()}
                    onSelectAgent={(agentId) => navigation.openAgent(agentId)}
                    onNudge={sendNudge}
                    onPreview={artifacts.openFileOutput}
                    onOpenWorkspaceResource={
                        openAgentWorkspaceResource
                    }
                    isOffline={isOffline}
                    stopRequested={stopRequested}
                />
            </div>
        );
    }

    return (
        <div className={styles.chatColumn}>
            <ChatPanel
                title={chatTitle}
                goal={features.goals ? goalsByConversation[activeConversationId] : undefined}
                onOpenGoal={() => openGoal(activeConversationId)}
                onRequestGoal={features.goals ? requestGoal : undefined}
                turns={turns}
                stalled={stalled}
                isOffline={isOffline}
                onSend={handleSend}
                onSendAnswers={handleSendAnswers}
                queue={queue}
                returned={returned}
                onRemoveQueued={removeQueuedMessage}
                onReturnedConsumed={consumeReturnedMessages}
                onStop={stopGeneration}
                isStreaming={isStreaming}
                stopRequested={stopRequested}
                networkAgentCount={agentCounts.total}
                networkRunningCount={agentCounts.running}
                onOpenNetwork={() => navigation.openNetwork()}
                onOpenArtifacts={() => artifacts.openConversationArtifacts(
                    activeConversationId,
                    tabGroupId,
                )}
                onSelectAgent={(agentId) => navigation.openAgent(agentId)}
                selectedProfileId={selectedProfileId}
                onProfileChange={pickConversationProfile}
                profileRefreshSignal={profilesHook.revision}
                onPreview={artifacts.openFileOutput}
                conversationId={activeConversationId}
                draft={draft}
                onDraftChange={setDraft}
            />
            {features.goals && <GoalRequestDialog request={goalRequest} profileId={selectedProfileId} onCreated={addConversation} onClose={closeRequest} />}
        </div>
    );
}
