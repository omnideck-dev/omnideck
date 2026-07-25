import { useCallback } from 'react';

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
    useWorkspaceResourceDesktopActions,
} from '../workspace/WorkspaceResourceDesktopAdapter.jsx';
import {
    useConversationSessionCommands,
    useConversationSessionState,
} from './session/ConversationSession.jsx';
import styles from '../../App.module.css';

/** Conversation-domain adapter for Chat and Agent Network modes. */
export default function ConversationDesktopView({ view, tabGroupId }) {
    const {
        activeConversationId,
        turns,
        draft,
        isStreaming,
        stopRequested,
        stalled,
        conversationProfileId,
    } = useConversationSessionState();
    const {
        sendMessage,
        sendNudge,
        stopGeneration,
        setDraft,
        setConversationProfileId,
    } = useConversationSessionCommands();
    const { profilesHook } = useAppData();
    const { defaultProfileId } = useAppSettings();
    const navigation = useDesktopNavigationCommands();
    const agentCounts = useAgentNetworkCounts();
    const artifacts = useArtifactDesktopActions();
    const {
        openAgentWorkspaceResource,
    } = useWorkspaceResourceDesktopActions();

    const selectedProfileId = conversationProfileId ?? defaultProfileId;
    const mode = view.navigationTarget?.kind || 'chat';
    const selectedAgentId = view.navigationTarget?.agentId || null;

    const handleSend = useCallback((message, attachments) => {
        if (isStreaming) {
            if (!stopRequested) sendNudge(message);
        } else {
            sendMessage(message, attachments, selectedProfileId);
        }
    }, [
        isStreaming,
        selectedProfileId,
        sendMessage,
        sendNudge,
        stopRequested,
    ]);

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
                    nudgeDisabled={stopRequested}
                />
            </div>
        );
    }

    return (
        <div className={styles.chatColumn}>
            <ChatPanel
                turns={turns}
                stalled={stalled}
                onSend={handleSend}
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
        </div>
    );
}
