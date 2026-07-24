import { useCallback, useRef } from 'react';

import { formatAgentName } from '../../utils/agentUtils.js';
import { useAgentState } from '../agent/AgentState.jsx';
import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    conversationExecutionSurfaceId,
    createConversationExecutionSurface,
} from './desktopSurfaces.js';
import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';

function paneContainingSurface(model, surfaceId) {
    return Object.entries(model.panes).find(([, pane]) => (
        pane.surfaceIds.includes(surfaceId)
    ))?.[0] || null;
}

function conversationSurface(model) {
    return model.surfaces.find((surface) => surface.kind === 'conversation') || null;
}

/** Return the region opposite the Conversation surface, falling back right. */
export function preferredCompanionPane(model) {
    const surface = conversationSurface(model);
    const conversationPaneId = surface
        ? paneContainingSurface(model, surface.id)
        : null;
    return conversationPaneId === DESKTOP_PANE_IDS.RIGHT
        ? DESKTOP_PANE_IDS.LEFT
        : DESKTOP_PANE_IDS.RIGHT;
}

/**
 * Adapts conversation-owned Browser/Terminal lifecycles to generic surfaces.
 *
 * The window manager only receives open/close operations and placement hints.
 * Root events may ensure an inactive surface exists; sub-agent surfaces open
 * only through the explicit command returned by this controller.
 */
export default function useConversationExecutionSurfaces({
    activeConversationId,
    windowManager,
}) {
    const { agents } = useAgentState();
    const dismissedSurfaceIdsRef = useRef(new Set());
    const modelRef = useRef(windowManager.model);
    modelRef.current = windowManager.model;

    const hasConversationSurface = useCallback(() => (
        Boolean(conversationSurface(modelRef.current))
    ), []);

    const buildSurface = useCallback(({
        conversationId,
        agentId,
        agentName,
        resourceId,
        isRoot,
    }) => createConversationExecutionSurface({
        conversationId,
        agentId,
        agentName: agentName ? formatAgentName(agentName) : null,
        resourceId,
        isRoot,
    }), []);

    const handleRootViewAvailable = useCallback((effect) => {
        const conversationId = effect.conversationId || activeConversationId;
        if (
            !conversationId
            || conversationId !== activeConversationId
            || !hasConversationSurface()
        ) {
            return;
        }
        const surface = buildSurface({
            ...effect,
            conversationId,
            isRoot: true,
        });
        if (!surface || dismissedSurfaceIdsRef.current.has(surface.id)) return;
        windowManager.commands.openSurface(
            surface,
            preferredCompanionPane(modelRef.current),
            { activate: false },
        );
    }, [
        activeConversationId,
        buildSurface,
        hasConversationSurface,
        windowManager.commands.openSurface,
    ]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
        handleRootViewAvailable,
    );

    const closeConversationViews = useCallback((conversationId) => {
        if (!conversationId) return;
        for (const surface of modelRef.current.surfaces) {
            if (
                surface.kind === 'conversation-execution'
                && surface.conversationId === conversationId
            ) {
                windowManager.commands.closeSurface(surface.id);
            }
        }
        const prefix = `conversation-execution:${conversationId}:`;
        dismissedSurfaceIdsRef.current = new Set(
            [...dismissedSurfaceIdsRef.current].filter(
                (surfaceId) => !surfaceId.startsWith(prefix),
            ),
        );
    }, [windowManager.commands.closeSurface]);

    const handleCloseConversationViews = useCallback(
        (effect) => closeConversationViews(effect.conversationId),
        [closeConversationViews],
    );
    useAppEffectSubscription(
        APP_EFFECT_TYPES.CLOSE_CONVERSATION_EXECUTION_VIEWS,
        handleCloseConversationViews,
    );

    const openAgentView = useCallback((agentId, resourceId) => {
        const agent = agents[agentId];
        if (
            !activeConversationId
            || !agent
            || !['browser', 'terminal'].includes(resourceId)
        ) {
            return;
        }
        const isRoot = agent.parentId === null;
        const surface = buildSurface({
            conversationId: activeConversationId,
            agentId,
            agentName: agent.name,
            resourceId,
            isRoot,
        });
        if (!surface) return;
        dismissedSurfaceIdsRef.current.delete(surface.id);
        windowManager.commands.openSurface(
            surface,
            preferredCompanionPane(modelRef.current),
        );
    }, [
        activeConversationId,
        agents,
        buildSurface,
        windowManager.commands.openSurface,
    ]);

    const closeExecutionSurface = useCallback((surface) => {
        if (surface?.kind !== 'conversation-execution') return;
        dismissedSurfaceIdsRef.current.add(
            conversationExecutionSurfaceId(
                surface.conversationId,
                surface.agentId,
                surface.resourceId,
                surface.isRoot,
            ),
        );
        windowManager.commands.closeSurface(surface.id);
    }, [windowManager.commands.closeSurface]);

    const preferredPaneId = useCallback(
        () => preferredCompanionPane(modelRef.current),
        [],
    );

    return {
        closeConversationViews,
        closeExecutionSurface,
        openAgentView,
        preferredPaneId,
    };
}
