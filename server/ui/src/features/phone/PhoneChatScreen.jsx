import { useCallback } from 'react';

import ChatInput from '../../components/ChatInput.jsx';
import ChatMessages from '../../components/ChatMessages.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import { label as conversationLabel } from '../../components/conversationSections.js';
import { useAppData } from '../../contexts/AppData.jsx';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import {
    useConversationSessionCommands,
    useConversationSessionState,
    useSelectedProfileId,
} from '../conversation/session/ConversationSession.jsx';
import GoalRequestDialog from '../goals/GoalRequestDialog.jsx';
import GoalStatus from '../goals/GoalStatus.jsx';
import { isGoalOpen, useGoals } from '../goals/GoalsState.jsx';
import useGoalRequests from '../goals/useGoalRequests.js';
import PhoneHeader from './PhoneHeader.jsx';
import styles from './PhoneChatScreen.module.css';

export default function PhoneChatScreen({ onBack, onPreview, onOpenArtifacts }) {
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
        stopGeneration,
        setDraft,
        pickConversationProfile,
    } = useConversationSessionCommands();
    const { profilesHook, features } = useAppData();
    const { goalsByConversation } = useGoals();
    const selectedProfileId = useSelectedProfileId();
    const { items, addConversation } = useConversationCatalog();
    const { request: goalRequest, requestGoal, closeRequest } = useGoalRequests(activeConversationId);

    const listed = items.find((item) => item.conversation_id === activeConversationId);
    const goal = features.goals ? goalsByConversation[activeConversationId] : undefined;

    const handleSend = useCallback((message, attachments) => (
        sendMessage(message, attachments, selectedProfileId)
    ), [selectedProfileId, sendMessage]);

    const handleSendAnswers = useCallback(async (goalId, answers) => {
        const result = await sendAnswers(goalId, answers, selectedProfileId);
        if (result && !result.ok) throw new Error(result.error || 'Your answers were not sent.');
        return { queued: Boolean(result?.queued) };
    }, [selectedProfileId, sendAnswers]);

    return (
        <div className={styles.screen} data-testid="phone-chat">
            <PhoneHeader
                onBack={onBack}
                backLabel="Chats"
                title={listed ? conversationLabel(listed) : 'New chat'}
                subtitle={goal ? <GoalStatus goal={goal} short compact /> : null}
                actions={listed && (
                    <IconButton
                        size="lg"
                        onClick={() => onOpenArtifacts(activeConversationId)}
                        title="Artifacts in this chat"
                        aria-label="Artifacts in this chat"
                        data-testid="phone-chat-artifacts"
                    >
                        <i className="bi bi-collection" aria-hidden="true" />
                    </IconButton>
                )}
            />
            <ChatMessages turns={turns} stalled={stalled} onPreview={onPreview} onStarterSelect={setDraft} />
            <div className={styles.composer}>
                <ChatInput
                    key={`composer:${activeConversationId}`}
                    conversationId={activeConversationId}
                    onSend={handleSend}
                    onSendAnswers={handleSendAnswers}
                    queue={queue}
                    returned={returned}
                    onRemoveQueued={removeQueuedMessage}
                    onReturnedConsumed={consumeReturnedMessages}
                    onStop={stopGeneration}
                    onRequestGoal={features.goals && !isGoalOpen(goal) ? requestGoal : undefined}
                    goal={goal}
                    isStreaming={isStreaming}
                    isOffline={isOffline}
                    stopRequested={stopRequested}
                    draft={draft}
                    onDraftConsumed={() => setDraft('')}
                    selectedProfileId={selectedProfileId}
                    onProfileChange={pickConversationProfile}
                    profileRefreshSignal={profilesHook.revision}
                    submitOnEnter={false}
                />
            </div>
            {features.goals && (
                <GoalRequestDialog
                    request={goalRequest}
                    profileId={selectedProfileId}
                    onCreated={addConversation}
                    onClose={closeRequest}
                />
            )}
        </div>
    );
}
