import ChatPanel from '../../components/ChatPanel.jsx';
import AgentNetworkView from '../agent/AgentNetworkView.jsx';
import styles from '../../App.module.css';

export default function MainSurface({
    view,
    paneId,
    selectedAgentId,
    agentCounts,
    session,
    selectedProfileId,
    profileRevision,
    actions,
}) {
    if (view === 'network') {
        return (
            <div className={selectedAgentId ? styles.chatColumn : styles.networkArea}>
                <AgentNetworkView
                    selectedAgentId={selectedAgentId}
                    turns={session.turns}
                    agentCounts={agentCounts}
                    onClose={actions.closeNetwork}
                    onOpenOverview={actions.openNetwork}
                    onSelectAgent={actions.selectAgent}
                    onNudge={session.sendNudge}
                    onPreview={actions.openPreview}
                    onOpenExecutionView={actions.openExecutionView}
                    nudgeDisabled={session.stopRequested}
                />
            </div>
        );
    }

    return (
        <div className={styles.chatColumn}>
            <ChatPanel
                turns={session.turns}
                stalled={session.stalled}
                onSend={actions.send}
                onStop={session.stopGeneration}
                isStreaming={session.isStreaming}
                stopRequested={session.stopRequested}
                networkAgentCount={agentCounts.total}
                networkRunningCount={agentCounts.running}
                onOpenNetwork={actions.openNetwork}
                onOpenArtifacts={() => actions.openArtifacts(
                    session.activeConversationId,
                    paneId,
                )}
                onSelectAgent={actions.selectAgent}
                selectedProfileId={selectedProfileId}
                onProfileChange={actions.changeProfile}
                profileRefreshSignal={profileRevision}
                onPreview={actions.openPreview}
                conversationId={session.activeConversationId}
                draft={session.draft}
                onDraftChange={session.setDraft}
            />
        </div>
    );
}
