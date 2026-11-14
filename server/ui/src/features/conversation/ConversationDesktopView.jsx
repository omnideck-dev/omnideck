import { isGoalOpen, useGoals } from '../goals/GoalsState.jsx';
import { useCallback, useEffect, useState } from 'react';

import ChatPanel from '../../components/ChatPanel.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import AgentNetworkView from '../agent/AgentNetworkView.jsx';
import useAgentNetworkCounts from '../agent/useAgentNetworkCounts.js';
import { useAppSettings } from '../app/AppSettings.jsx';
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
} from './session/ConversationSession.jsx';
import styles from '../../App.module.css';
import { useGoalDesktopActions } from '../goals/GoalDesktopView.jsx';
import GoalDialog from '../goals/GoalDialog.jsx';

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
        conversationProfileId,
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
        setConversationProfileId,
    } = useConversationSessionCommands();
    const { profilesHook, features } = useAppData();
    const { goalsByConversation, loadGoal } = useGoals();
    const { openGoal } = useGoalDesktopActions();
    const { defaultProfileId } = useAppSettings();
    const navigation = useDesktopNavigationCommands();
    const agentCounts = useAgentNetworkCounts();
    const artifacts = useArtifactDesktopActions();
    const {
        openAgentWorkspaceResource,
    } = useWorkspaceResourceDesktopActions();

    const selectedProfileId = conversationProfileId ?? defaultProfileId;
    const navigationTarget = navigationTargetForView(view);
    const mode = navigationTarget?.kind || 'chat';
    const selectedAgentId = navigationTarget?.agentId || null;
    const [goalRequest, setGoalRequest] = useState(null);

    useEffect(() => {
        setGoalRequest(null);
    }, [activeConversationId, features.goals, mode]);

    const requestGoal = useCallback((request = {}) => {
        if (!features.goals || isOffline || stopRequested) return;
        if (isGoalOpen(goalsByConversation[activeConversationId]) && !request.objective?.trim()) {
            openGoal(activeConversationId);
            request.onStarted?.();
            return;
        }
        setGoalRequest({ ...request, conversationId: activeConversationId });
    }, [features.goals, isOffline, stopRequested, activeConversationId, goalsByConversation, openGoal]);

    const handleSend = useCallback((message, attachments) => (
        sendMessage(message, attachments, selectedProfileId)
    ), [selectedProfileId, sendMessage]);

    const handleSendAnswers = useCallback(async (goalId, answers) => {
        const conversationId = activeConversationId;
        const result = await sendAnswers(goalId, answers, selectedProfileId);
        if (result && !result.ok) throw new Error(result.error || 'Your answers were not sent.');
        // Read the goal now so the composer sees the saved answers without waiting for the next poll.
        const snapshot = await loadGoal(conversationId);
        return { goal: snapshot?.goal, queued: Boolean(result?.queued) };
    }, [activeConversationId, loadGoal, selectedProfileId, sendAnswers]);

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
                onProfileChange={setConversationProfileId}
                profileRefreshSignal={profilesHook.revision}
                onPreview={artifacts.openFileOutput}
                conversationId={activeConversationId}
                draft={draft}
                onDraftChange={setDraft}
            />
            {features.goals && goalRequest?.conversationId === activeConversationId && <GoalDialog
                key={activeConversationId}
                conversationId={activeConversationId}
                profileId={selectedProfileId}
                initialObjective={goalRequest.objective}
                onStarted={() => goalRequest.onStarted?.()}
                onClose={() => {
                    goalRequest.onClosed?.();
                    setGoalRequest((current) => current === goalRequest ? null : current);
                }}
            />}
        </div>
    );
}
