import { useCallback } from 'react';

import {
    useActiveConversationId,
    useConversationSessionState,
} from '../conversation/session/ConversationSession.jsx';
import {
    useAppEffectDispatch,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useDesktopViewCommands,
    useDesktopViewCatalog,
    useFocusedViewId,
} from '../desktop/DesktopViewRuntime.jsx';
import useWorkspaceResourceDesktopViews from './useWorkspaceResourceDesktopViews.js';
import useActiveWorkspaceResource from './useActiveWorkspaceResource.js';
import WorkspaceResourceView from './WorkspaceResourceView.jsx';

/**
 * Installs Workspace lifecycle reactions which are independent of rendering a
 * particular Browser or Terminal View.
 */
export function WorkspaceResourceDesktopEffects() {
    const desktopModel = useDesktopViewCatalog();
    const desktopCommands = useDesktopViewCommands();
    const activeConversationId = useActiveConversationId();
    useWorkspaceResourceDesktopViews({
        activeConversationId,
        desktopModel,
        desktopCommands,
    });
    return null;
}

/**
 * Commands that let other domains request Workspace-owned Desktop behavior
 * without constructing Workspace resource Views themselves.
 */
export function useWorkspaceResourceDesktopActions() {
    const dispatchAppEffect = useAppEffectDispatch();
    const openAgentWorkspaceResource = useCallback((agentId, resourceId) => {
        dispatchAppEffect({
            type: APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE,
            agentId,
            resourceId,
        });
    }, [dispatchAppEffect]);
    return { openAgentWorkspaceResource };
}

/**
 * Per-View adapter from serializable Workspace identity to the domain renderer.
 *
 * Only the focused root Browser View owns the browser-control side channel.
 * Merely moving the View does not change which agent/resource it represents,
 * and sub-agent Browsers remain screenshot-backed, read-only Views.
 */
export default function WorkspaceResourceDesktopView({ view, active }) {
    const focusedViewId = useFocusedViewId();
    const {
        activeConversationId,
        isStreaming,
    } = useConversationSessionState();
    // Browser control is an exclusive lock, not a render subscription. Every
    // visible Browser may paint Workspace screenshots, but only the focused
    // root Browser may own the conversation's single control WebSocket.
    const ownsBrowserSession = (
        view.id === focusedViewId
        && view.isRoot
    );
    const { browser } = useActiveWorkspaceResource({
        conversationId: activeConversationId,
        isStreaming,
        activeView: ownsBrowserSession ? view : null,
    });
    return (
        <WorkspaceResourceView
            agentId={view.agentId}
            resourceId={view.resourceId}
            browser={browser}
            active={active}
        />
    );
}
