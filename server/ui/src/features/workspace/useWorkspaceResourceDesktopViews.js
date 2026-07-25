import { useCallback, useRef } from 'react';

import { formatAgentName } from '../../utils/agentUtils.js';
import { useAgentState } from '../agent/AgentState.jsx';
import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    createWorkspaceResourceView,
} from '../desktop/desktopViews.js';

function conversationView(model) {
    return model.openViews.find((view) => view.type === 'conversation') || null;
}

/**
 * Adapts Workspace-owned Browser/Terminal lifecycles to generic Views.
 *
 * Desktop Layout only receives open/close operations and placement hints.
 * Root events may ensure an inactive view exists; sub-agent views open
 * only through the explicit command returned by this controller.
 */
export default function useWorkspaceResourceDesktopViews({
    activeConversationId,
    desktopModel,
    desktopCommands,
}) {
    const { agents } = useAgentState();
    const dismissedViewIdsRef = useRef(new Set());
    // App effects may fire between renders. Keeping the latest model in a ref
    // gives stable subscriptions access to current placement without making
    // the effect handlers depend on every drag, resize, or tab selection.
    const modelRef = useRef(desktopModel);
    modelRef.current = desktopModel;

    const hasConversationView = useCallback(() => (
        Boolean(conversationView(modelRef.current))
    ), []);

    const buildView = useCallback(({
        conversationId,
        agentId,
        agentName,
        resourceId,
        isRoot,
    }) => createWorkspaceResourceView({
        conversationId,
        agentId,
        agentName: agentName ? formatAgentName(agentName) : null,
        resourceId,
        isRoot,
    }), []);

    const handleRootResourceAvailable = useCallback((effect) => {
        const conversationId = effect.conversationId || activeConversationId;
        if (
            !conversationId
            || conversationId !== activeConversationId
            || !hasConversationView()
        ) {
            return;
        }
        const view = buildView({
            ...effect,
            conversationId,
            isRoot: true,
        });
        if (!view || dismissedViewIdsRef.current.has(view.id)) return;
        desktopCommands.openView(view, {
            tabGroupId: desktopCommands.preferredTabGroupId(),
            activate: false,
        });
    }, [
        activeConversationId,
        buildView,
        hasConversationView,
        desktopCommands.openView,
        desktopCommands.preferredTabGroupId,
    ]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE,
        handleRootResourceAvailable,
    );

    const closeConversationWorkspaceViews = useCallback((conversationId) => {
        if (!conversationId) return;
        const viewIds = modelRef.current.openViews
            .filter((view) => (
                view.type === 'workspace-resource'
                && view.conversationId === conversationId
            ))
            .map((view) => view.id);
        desktopCommands.closeViews(viewIds);
        const prefix = `workspace-resource:${conversationId}:`;
        dismissedViewIdsRef.current = new Set(
            [...dismissedViewIdsRef.current].filter(
                (viewId) => !viewId.startsWith(prefix),
            ),
        );
    }, [desktopCommands.closeViews]);

    const handleCloseConversationViews = useCallback(
        (effect) => closeConversationWorkspaceViews(effect.conversationId),
        [closeConversationWorkspaceViews],
    );
    useAppEffectSubscription(
        APP_EFFECT_TYPES.CLOSE_CONVERSATION_WORKSPACE_VIEWS,
        handleCloseConversationViews,
    );

    const openAgentWorkspaceResource = useCallback((agentId, resourceId) => {
        const agent = agents[agentId];
        if (
            !activeConversationId
            || !agent
            || !['browser', 'terminal'].includes(resourceId)
        ) {
            return;
        }
        const isRoot = agent.parentId === null;
        const view = buildView({
            conversationId: activeConversationId,
            agentId,
            agentName: agent.name,
            resourceId,
            isRoot,
        });
        if (!view) return;
        dismissedViewIdsRef.current.delete(view.id);
        desktopCommands.openView(view, {
            tabGroupId: desktopCommands.preferredTabGroupId(),
        });
    }, [
        activeConversationId,
        agents,
        buildView,
        desktopCommands.openView,
        desktopCommands.preferredTabGroupId,
    ]);

    const handleOpenAgentResource = useCallback((effect) => {
        openAgentWorkspaceResource(effect.agentId, effect.resourceId);
    }, [openAgentWorkspaceResource]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE,
        handleOpenAgentResource,
    );

    const handleViewsClosing = useCallback((effect) => {
        const closingConversationIds = new Set(
            effect.views
                .filter((view) => view.type === 'conversation')
                .map((view) => view.navigationTarget?.conversationId)
                .filter(Boolean),
        );

        // An explicitly closed Workspace View remains dismissed until the
        // conversation changes. If the conversation itself is closing, its
        // dismissal history is cleared instead.
        for (const view of effect.views) {
            if (
                view.type === 'workspace-resource'
                && !closingConversationIds.has(view.conversationId)
            ) {
                dismissedViewIdsRef.current.add(view.id);
            }
        }
        for (const conversationId of closingConversationIds) {
            closeConversationWorkspaceViews(conversationId);
        }
    }, [closeConversationWorkspaceViews]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
        handleViewsClosing,
    );

}
