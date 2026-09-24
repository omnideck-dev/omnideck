import { useMemo } from 'react';

import useBrowserTabs from './useBrowserTabs.js';
import { useWorkspaceState } from './WorkspaceState.jsx';
import {
    workspaceResourceIdentityForView,
} from './workspaceResourceDesktopViews.js';

/**
 * Adapts one visible root Browser View to the shared browser-control channel.
 *
 * Terminal Views are rejected by their resource identity, while read-only
 * sub-agent Views pass `null`. In both cases the hook leaves the channel
 * disabled while still returning the stable Browser runtime shape.
 */
export default function useBrowserControlForWorkspaceView({
    conversationId,
    isStreaming,
    visibleView = null,
}) {
    const workspaceState = useWorkspaceState();
    const visibleIdentity = workspaceResourceIdentityForView(visibleView);
    const visibleBrowserAgentId = visibleView?.type === 'workspace-resource'
        && visibleIdentity.resourceId === 'browser'
        ? visibleIdentity.agentId
        : null;
    const agentWorkspace = visibleBrowserAgentId
        ? workspaceState.byAgentId[visibleBrowserAgentId]
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
            && visibleBrowserAgentId !== null,
        agentTabs: browserTabsList,
        sessionKey: visibleBrowserAgentId,
    });

    return {
        browser: {
            ...browser,
            agentId: visibleBrowserAgentId,
        },
    };
}
