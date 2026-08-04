import React from 'react';
import ChatMessages from './ChatMessages.jsx';
import ChatInput from './ChatInput.jsx';
import ContextMeter from './ContextMeter.jsx';
import { formatAgentName } from '../utils/agentUtils.js';
import StatusDot from './StatusDot.jsx';
import { useAgentState } from '../features/agent/AgentState.jsx';
import styles from './ChatPanel.module.css';

/**
 * Chat panel for talking to the root agent. A title bar across the top
 * carries the conversation title, turn count, and context meter; below
 * it the scrollable message list and the input bar.
 *
 * When sub-agents have been spawned, a network indicator appears in the
 * title bar so the user can navigate to the full agent network view.
 */
export default function ChatPanel({ turns, stalled = false, isOffline = false, onSend, onStop, isStreaming, stopRequested = false, attachment, onPreview, onSelectAgent, networkAgentCount = 0, networkRunningCount, onOpenNetwork, onOpenArtifacts, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId, draft, onDraftChange }) {
    // The title bar reflects the root agent; read it straight from the agent
    // tree rather than receiving it as a prop.
    const agentState = useAgentState();
    const rootAgent = agentState.rootId ? agentState.agents[agentState.rootId] : null;

    // A turn is one user message and its response. Title falls back to the
    // agent name until the live conversation title is wired up.
    const turnCount = Array.isArray(turns) ? turns.length : 0;
    const title = rootAgent?.name ? formatAgentName(rootAgent.name) : 'Chat';

    return (
        <div className={styles.panel}>
            <div className={styles.titleBar} data-testid="chat-title-bar">
                <div className={styles.left}>
                    <span className={styles.title} data-testid="chat-title">{title}</span>
                    {turnCount > 0 && (
                        <span className={styles.turns} data-testid="chat-turns">
                            {turnCount} turn{turnCount !== 1 ? 's' : ''}
                        </span>
                    )}
                    <ContextMeter contextUsage={rootAgent?.contextUsage} />
                </div>
                <button
                    className={styles.artifactsBtn}
                    onClick={onOpenArtifacts}
                    title="Files produced in this conversation"
                    data-testid="conversation-artifacts-trigger"
                >
                    <i className="bi bi-collection" />
                    <span>Artifacts</span>
                </button>
                {networkAgentCount > 0 && (
                    <button className={styles.networkBtn} onClick={onOpenNetwork} title="Open agent network view" data-testid="network-indicator">
                        <StatusDot status={networkRunningCount > 0 ? 'running' : 'complete'} />
                        <span>{networkAgentCount} agent{networkAgentCount !== 1 ? 's' : ''}</span>
                    </button>
                )}
            </div>
            {isOffline && (
                <div
                    className={styles.connectionStatus}
                    data-testid="connection-status"
                    role="status"
                >
                    <i className="bi bi-wifi-off" aria-hidden="true" />
                    <span>Offline</span>
                </div>
            )}
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
