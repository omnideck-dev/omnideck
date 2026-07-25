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
 * Request an explicit sub-agent resource without teaching Conversation how a
 * Workspace resource becomes a Desktop View.
 */
export function useOpenAgentWorkspaceResource() {
    const dispatchAppEffect = useAppEffectDispatch();
    return useCallback((agentId, resourceId) => {
        dispatchAppEffect({
            type: APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE,
            agentId,
            resourceId,
        });
    }, [dispatchAppEffect]);
}

/**
 * Per-View adapter from serializable Workspace identity to the domain renderer.
 *
 * Only the active Browser View owns the browser-control side channel. Merely
 * moving the View does not change which agent/resource it represents.
 */
export default function WorkspaceResourceDesktopView({ view, active }) {
    const {
        activeConversationId,
        isStreaming,
    } = useConversationSessionState();
    const { browser } = useActiveWorkspaceResource({
        conversationId: activeConversationId,
        isStreaming,
        activeView: active ? view : null,
    });
    return (
        <WorkspaceResourceView
            agentId={view.agentId}
            resourceId={view.resourceId}
            browser={browser}
        />
    );
}
