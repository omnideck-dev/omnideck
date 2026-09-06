import React from 'react';
import ChatMessages from './ChatMessages.jsx';
import ChatInput from './ChatInput.jsx';
import ConversationHeader from '../features/conversation/details/ConversationHeader.jsx';
import { buildConversationDetails } from '../features/conversation/details/conversationDetailsModel.js';
import { formatAgentName } from '../utils/agentUtils.js';
import { useAgentState } from '../features/agent/AgentState.jsx';
import styles from './ChatPanel.module.css';

/**
 * Chat panel for talking to the root agent. A title bar across the top
 * carries the title and Details disclosure; below it the message list
 * and input bar. Details receives workspace/navigation data from its adapter.
 */
export default function ChatPanel({ turns, stalled = false, isOffline = false, onSend, onStop, isStreaming, stopRequested = false, attachment, onPreview, onSelectAgent, onOpenNetwork, onOpenArtifacts, onOpenWorkspaceResource, detailsModel, conversationTitle, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId, draft, onDraftChange }) {
    // Keep an agent-name fallback while a conversation title is being generated.
    const agentState = useAgentState();
    const rootAgent = agentState.rootId ? agentState.agents[agentState.rootId] : null;

    const title = conversationTitle || (rootAgent?.name ? formatAgentName(rootAgent.name) : 'Chat');
    const model = detailsModel || buildConversationDetails({ conversationId, turns, ...agentState });
    const selectResource = (row) => {
        if (row.id === 'artifacts') onOpenArtifacts?.();
        else if (row.id === 'agents') onOpenNetwork?.();
        else onOpenWorkspaceResource?.(row.agentId, row.resourceId);
    };

    return (
        <div className={styles.panel}>
            <ConversationHeader title={title} conversationId={conversationId} model={model} onSelect={selectResource} />
            <ChatMessages turns={turns} stalled={stalled} onPreview={onPreview} onSelectAgent={onSelectAgent} onStarterSelect={onDraftChange} />
            {/* Keyed by conversation so switching chats remounts the input,
                discarding any unsent text instead of carrying it over. */}
            <ChatInput
                key={conversationId}
                onSend={onSend}
                onStop={onStop}
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
