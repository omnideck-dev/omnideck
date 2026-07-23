import ChatPanel from '../../components/ChatPanel.jsx';
import AgentNetworkView from '../agent/AgentNetworkView.jsx';
import styles from '../../App.module.css';
import DesktopDock from './DesktopDock.jsx';

export default function MainSurface({
    view,
    selectedAgentId,
    dockVisible,
    dockExpanded,
    includeCustomAppInDock,
    dock,
    preview,
    browser,
    customApps,
    agentCounts,
    session,
    selectedProfileId,
    profileRevision,
    actions,
}) {
    return (
        <>
            {view === 'network' && (
                <div
                    className={selectedAgentId ? styles.chatColumn : styles.networkArea}
                    style={selectedAgentId
                        ? { width: dockVisible ? `${dock.splitPosition}%` : '100%' }
                        : undefined}
                >
                    <AgentNetworkView
                        selectedAgentId={selectedAgentId}
                        agentCounts={agentCounts}
                        onClose={actions.closeNetwork}
                        onOpenOverview={actions.openNetwork}
                        onSelectAgent={actions.selectAgent}
                        onNudge={session.sendNudge}
                        onPreview={actions.openPreview}
                        nudgeDisabled={session.stopRequested}
                    />
                </div>
            )}

            {/* Keep the conversation mounted while another surface is visible. */}
            <div
                className={`${styles.chatColumn} ${view !== 'chat' ? styles.hidden : ''}`}
                style={{
                    width: dockVisible && !dockExpanded
                        ? `${dock.splitPosition}%`
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

            <DesktopDock
                visible={dockVisible}
                expanded={dockExpanded}
                includeCustomApp={includeCustomAppInDock}
                dock={dock}
                customApps={customApps}
                preview={preview}
                browser={browser}
                actions={actions}
            />
        </>
    );
}
