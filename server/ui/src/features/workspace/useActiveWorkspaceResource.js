import { useMemo } from 'react';

import useBrowserTabs from './useBrowserTabs.js';
import { useWorkspaceState } from './WorkspaceState.jsx';
import {
    workspaceResourceIdentityForView,
} from './workspaceResourceDesktopViews.js';

/** Owns the one browser-control side channel used by visible Browser views. */
export default function useActiveWorkspaceResource({
    conversationId,
    isStreaming,
    activeView = null,
}) {
    const workspaceState = useWorkspaceState();
    const activeIdentity = workspaceResourceIdentityForView(activeView);
    const activeBrowserAgentId = activeView?.type === 'workspace-resource'
        && activeIdentity.resourceId === 'browser'
        ? activeIdentity.agentId
        : null;
    const agentWorkspace = activeBrowserAgentId
        ? workspaceState.byAgentId[activeBrowserAgentId]
        : null;

    const browserTabs = agentWorkspace?.browserTabs || {};
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
