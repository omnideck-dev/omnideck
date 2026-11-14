import React, { useRef } from 'react';
import ConversationControls from './ConversationControls.jsx';
import ChatMessages from './ChatMessages.jsx';
import ChatInput from './ChatInput.jsx';
import GoalHeadline from '../features/goals/GoalHeadline.jsx';
import { formatAgentName } from '../utils/agentUtils.js';
import { useAgentState } from '../features/agent/AgentState.jsx';
import styles from './ChatPanel.module.css';

/** One conversation header, transcript, and composer. */
export default function ChatPanel({ turns, stalled = false, isOffline = false, onSend, onSendAnswers, queue, returned, onRemoveQueued, onReturnedConsumed, onStop, isStreaming, stopRequested = false, attachment, onPreview, onSelectAgent, networkAgentCount = 0, networkRunningCount = 0, onOpenNetwork, onOpenArtifacts, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId, draft, onDraftChange, onRequestGoal, onOpenGoal, goal }) {
    const headerRef = useRef(null);
    const agentState = useAgentState();
    const rootAgent = agentState.rootId ? agentState.agents[agentState.rootId] : null;

    // A turn is one user message and its response. Keep this existing metadata
    // available in Details without repeating the conversation tab title.
    const turnCount = Array.isArray(turns) ? turns.length : 0;
    const title = rootAgent?.name ? formatAgentName(rootAgent.name) : 'Chat';

    const renderControls = () => <ConversationControls
        key={conversationId} anchorRef={headerRef} agentName={title} turnCount={turnCount}
        contextUsage={rootAgent?.contextUsage}
        onOpenArtifacts={onOpenArtifacts} onOpenNetwork={onOpenNetwork}
        networkAgentCount={networkAgentCount} networkRunningCount={networkRunningCount} />;

    return (
        <div className={styles.panel} data-testid="chat-panel">
            <header ref={headerRef} className={styles.header} data-testid="chat-title-bar" aria-label="Conversation header">
                {goal ? <div className={styles.goalHeading}>
                    <GoalHeadline goal={goal} onOpen={onOpenGoal} />
                </div> : <span className={styles.title}>{title}</span>}
                {renderControls()}
            </header>
            <ChatMessages turns={turns} stalled={stalled} onPreview={onPreview} onSelectAgent={onSelectAgent} onStarterSelect={onDraftChange} />
            {/* Keyed by conversation so switching chats remounts the input —
                its own unsent-draft state is restored from local storage per
                conversationId rather than carried over from the old chat. */}
            <ChatInput
                key={`composer:${conversationId}`}
                conversationId={conversationId}
                onSend={onSend}
                onSendAnswers={onSendAnswers}
                queue={queue}
                returned={returned}
                onRemoveQueued={onRemoveQueued}
                onReturnedConsumed={onReturnedConsumed}
                onStop={onStop}
                onRequestGoal={onRequestGoal}
                goal={goal}
                isStreaming={isStreaming}
                isOffline={isOffline}
                stopRequested={stopRequested}
                attachment={attachment}
                draft={draft}
                onDraftConsumed={() => onDraftChange('')}
                selectedProfileId={selectedProfileId}
                onProfileChange={onProfileChange}
                profileRefreshSignal={profileRefreshSignal}
            />
        </div>
    );
}
