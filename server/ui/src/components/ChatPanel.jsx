import React, { useState } from 'react';
import ChatMessages from './ChatMessages.jsx';
import ChatInput from './ChatInput.jsx';
import ContextMeter from './ContextMeter.jsx';
import { formatAgentName } from './AgentCard.jsx';
import StatusDot from './StatusDot.jsx';
import ArtifactsDrawer from './artifacts/ArtifactsDrawer.jsx';
import { useAgentState } from '../hooks/useAgentState.jsx';
import styles from './ChatPanel.module.css';

/**
 * Chat panel for talking to the root agent. A title bar across the top
 * carries the conversation title, turn count, and context meter; below
 * it the scrollable message list and the input bar.
 *
 * When sub-agents have been spawned, a network indicator appears in the
 * title bar so the user can navigate to the full agent network view.
 */
export default function ChatPanel({ turns, onSend, onStop, isStreaming, stopRequested = false, attachment, onPreview, onSelectAgent, networkActivated, networkAgentCount, networkRunningCount, onOpenNetwork, selectedProfileId, onProfileChange, profileRefreshSignal, conversationId, draft, onDraftChange }) {
    const [drawerOpen, setDrawerOpen] = useState(false);

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
                    onClick={() => setDrawerOpen(true)}
                    title="Files produced in this conversation"
                    data-testid="artifacts-drawer-trigger"
                >
                    <i className="bi bi-collection" />
                    <span>Artifacts</span>
                </button>
                {networkActivated && (
                    <button className={styles.networkBtn} onClick={onOpenNetwork} title="Open agent network view" data-testid="network-indicator">
                        <StatusDot status={networkRunningCount > 0 ? 'running' : 'complete'} />
                        <span>{networkAgentCount} agent{networkAgentCount !== 1 ? 's' : ''}</span>
                    </button>
                )}
            </div>
            <ChatMessages turns={turns} onPreview={onPreview} onSelectAgent={onSelectAgent} onStarterSelect={onDraftChange} />
            {/* Keyed by conversation so switching chats remounts the input,
                discarding any unsent text instead of carrying it over. */}
            <ChatInput
                key={conversationId}
                onSend={onSend}
                onStop={onStop}
                isStreaming={isStreaming}
                stopRequested={stopRequested}
                attachment={attachment}
                draft={draft}
                onDraftConsumed={() => onDraftChange('')}
                selectedProfileId={selectedProfileId}
                onProfileChange={onProfileChange}
                profileRefreshSignal={profileRefreshSignal}
            />
            {drawerOpen && (
                <ArtifactsDrawer
                    conversationId={conversationId}
                    onPreview={onPreview}
                    onClose={() => setDrawerOpen(false)}
                />
            )}
        </div>
    );
}
