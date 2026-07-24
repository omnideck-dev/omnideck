import { useMemo } from 'react';

import useBrowserTabs from './useBrowserTabs.js';
import { useWorkspaceState } from './WorkspaceState.jsx';

/** Owns the one browser-control side channel used by visible Browser surfaces. */
export default function useConversationExecutionView({
    conversationId,
    isStreaming,
    activeSurface = null,
}) {
    const workspaceState = useWorkspaceState();
    const activeBrowserAgentId = activeSurface?.kind === 'conversation-execution'
        && activeSurface.resourceId === 'browser'
        ? activeSurface.agentId
        : null;
    const executionState = activeBrowserAgentId
        ? workspaceState.byAgentId[activeBrowserAgentId]
        : null;

    const browserTabs = executionState?.browserTabs || {};
    const browserTabsList = useMemo(() => {
        const entries = Object.entries(browserTabs).map(([key, snapshot]) => ({
            id: Number(key),
            snapshot,
        }));
        entries.sort((a, b) => a.id - b.id);
        return entries;
    }, [browserTabs]);

    const browser = useBrowserTabs({
        conversationId,
        canControl: !isStreaming,
        enabled: browserTabsList.length > 0
            && activeBrowserAgentId !== null,
        agentTabs: browserTabsList,
    });

    return {
        browser: {
            ...browser,
            agentId: activeBrowserAgentId,
        },
    };
}
