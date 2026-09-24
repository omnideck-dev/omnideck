import { useCallback, useState } from 'react';

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
import useBrowserControlForWorkspaceView from
    './useBrowserControlForWorkspaceView.js';
import {
    workspaceResourceIdentityForView,
} from './workspaceResourceDesktopViews.js';
import WorkspaceResourceView from './WorkspaceResourceView.jsx';
import BrowserSaveModal from '../browser/BrowserSaveModal.jsx';
import { useAppData } from '../../contexts/AppData.jsx';
import { useToast } from '../../components/ToastProvider.jsx';

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
            type: APP_EFFECT_TYPES
                .OPEN_AGENT_WORKSPACE_RESOURCE_REQUESTED,
            payload: {
                agentId,
                resourceId,
            },
        });
    }, [dispatchAppEffect]);
    return { openAgentWorkspaceResource };
}

/**
 * Per-View adapter from serializable Workspace identity to the domain renderer.
 *
 * Only a visible root Browser View owns the browser-control side channel.
 * Merely moving the View does not change which agent/resource it represents,
 * and sub-agent Browsers remain screenshot-backed, read-only Views.
 */
export default function WorkspaceResourceDesktopView({ view, visible }) {
    const {
        activeConversationId,
        isStreaming,
    } = useConversationSessionState();
    const [showSaveBrowser, setShowSaveBrowser] = useState(false);
    // There is one root Browser View per conversation and one host per View.
    // `visible` keeps hidden tabs from streaming without confusing Desktop
    // focus—which may remain on Chat in the opposite tab group—with whether
    // the visibly selected Browser should expose its control channel.
    const {
        agentId,
        resourceId,
        isRoot,
    } = workspaceResourceIdentityForView(view);
    const ownsBrowserSession = visible && isRoot;
    const { browser } = useBrowserControlForWorkspaceView({
        conversationId: activeConversationId,
        isStreaming,
        visibleView: ownsBrowserSession ? view : null,
    });
    return (
        <>
            <WorkspaceResourceView
                agentId={agentId}
                resourceId={resourceId}
                browser={browser}
                visible={visible}
                onSaveBrowserState={() => setShowSaveBrowser(true)}
            />
            {showSaveBrowser && (
                <TakeoverSaveModal
                    conversationId={activeConversationId}
                    onClose={() => setShowSaveBrowser(false)}
                />
            )}
        </>
    );
}

function TakeoverSaveModal({ conversationId, onClose }) {
    const { profilesHook } = useAppData();
    const { addToast } = useToast();
    return (
        <BrowserSaveModal
            conversationId={conversationId}
            onClose={onClose}
            onSaved={(profile, assigned, agentName) => {
                if (assigned) profilesHook.refresh();
                addToast(
                    assigned
                        ? `Saved “${profile.name}” and assigned it to ${agentName || 'the agent'}.`
                        : `Saved Browser state to “${profile.name}”.`,
                    { type: 'success' },
                );
            }}
        />
    );
}
