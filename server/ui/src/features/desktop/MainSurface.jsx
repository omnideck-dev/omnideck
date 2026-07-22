import AgentActivityView from '../../components/AgentActivityView.jsx';
import AgentNetwork from '../../components/AgentNetwork.jsx';
import ChatPanel from '../../components/ChatPanel.jsx';
import styles from '../../App.module.css';
import PreviewPanel from '../workspace/PreviewPanel.jsx';
import PersistentCustomAppLayer from '../customApps/PersistentCustomAppLayer.jsx';

export default function MainSurface({
    view,
    selectedAgentId,
    hasPreview,
    workspaceVisible,
    workspaceSplit,
    preview,
    browser,
    customApps,
    agentState,
    agentCounts,
    session,
    selectedProfileId,
    profileRevision,
    actions,
}) {
    return (
        <>
            {view === 'network' && !selectedAgentId && (
                <div className={styles.networkArea}>
                    <AgentNetwork
                        onClose={actions.closeNetwork}
                        onSelectAgent={actions.selectAgent}
                        agentCount={agentCounts.total}
                    />
                </div>
            )}

            {view === 'network' && selectedAgentId && (
                <div
                    className={styles.chatColumn}
                    style={{ width: hasPreview ? `${preview.splitPosition}%` : '100%' }}
                >
                    <AgentActivityView
                        agentId={selectedAgentId}
                        onBack={actions.openNetwork}
                        onSelectAgent={actions.selectAgent}
                        onNudge={session.sendNudge}
                        onPreview={actions.openPreview}
                        nudgeDisabled={session.stopRequested}
                    />
                </div>
            )}

            {/* Keep the conversation mounted while another surface is visible. */}
            <div
                className={`${styles.chatColumn} ${view !== 'chat' && !workspaceSplit ? styles.hidden : ''}`}
                style={{
                    width: (hasPreview && view === 'chat') || workspaceSplit
                        ? `${preview.splitPosition}%`
                        : '100%',
                }}
            >
                <ChatPanel
                    turns={session.turns}
                    stalled={session.stalled}
                    onSend={actions.send}
                    onStop={session.stopGeneration}
                    isStreaming={session.isStreaming}
                    stopRequested={session.stopRequested}
                    networkActivated={agentState.networkActivated}
                    networkAgentCount={agentCounts.total}
                    networkRunningCount={agentCounts.running}
                    onOpenNetwork={actions.openNetwork}
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

            <PersistentCustomAppLayer
                customApps={customApps}
                visible={workspaceVisible}
                preview={preview}
                browser={browser}
            />

            {hasPreview && <PreviewPanel preview={preview} browser={browser} />}
        </>
    );
}
