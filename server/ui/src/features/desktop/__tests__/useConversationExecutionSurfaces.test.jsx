import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AgentProvider, useAgentDispatch } from '../../agent/AgentState.jsx';
import {
    AppEffectsProvider,
    useAppEffectDispatch,
} from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import {
    createArtifactSurface,
    createDestinationSurface,
} from '../desktopSurfaces.js';
import useConversationExecutionSurfaces from '../useConversationExecutionSurfaces.js';
import useDesktopWindowManager, {
    DESKTOP_PANE_IDS,
} from '../useDesktopWindowManager.jsx';

const CONVERSATION_ID = 'conversation-1';
const CHAT = createDestinationSurface({
    kind: 'chat',
    conversationId: CONVERSATION_ID,
});
const APP = {
    id: 'custom-app:text-lab',
    kind: 'custom-app',
    group: 'custom-app',
    label: 'Text Lab',
};
const ARTIFACT = createArtifactSurface({
    id: 'artifact-1',
    filename: 'report.md',
    conversation_id: CONVERSATION_ID,
});

function wrapper({ children }) {
    return (
        <AppEffectsProvider>
            <AgentProvider>{children}</AgentProvider>
        </AppEffectsProvider>
    );
}

function useHarness() {
    const windowManager = useDesktopWindowManager({ initialSurface: CHAT });
    const controller = useConversationExecutionSurfaces({
        activeConversationId: CONVERSATION_ID,
        windowManager,
    });
    return {
        windowManager,
        controller,
        dispatchEffect: useAppEffectDispatch(),
        dispatchAgent: useAgentDispatch(),
    };
}

function rootViewEffect(resourceId, agentId = 'root-1') {
    return {
        type: APP_EFFECT_TYPES.ROOT_EXECUTION_VIEW_AVAILABLE,
        conversationId: CONVERSATION_ID,
        agentId,
        agentName: 'root',
        resourceId,
    };
}

describe('useConversationExecutionSurfaces', () => {
    it('adds a root Browser tab opposite Chat without taking focus', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));

        const browserId = 'conversation-execution:conversation-1:root:browser';
        expect(result.current.windowManager.model.panes.right.surfaceIds)
            .toEqual([browserId]);
        expect(result.current.windowManager.model.focusedPaneId)
            .toBe(DESKTOP_PANE_IDS.LEFT);
        expect(result.current.windowManager.model.panes.left.activeSurfaceId)
            .toBe(CHAT.id);
    });

    it('does not replace the active tab in the companion pane', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => result.current.windowManager.commands.openSurface(
            APP,
            DESKTOP_PANE_IDS.RIGHT,
        ));
        act(() => result.current.dispatchEffect(rootViewEffect('terminal')));

        expect(result.current.windowManager.model.panes.right.surfaceIds)
            .toEqual([
                APP.id,
                'conversation-execution:conversation-1:root:terminal',
            ]);
        expect(result.current.windowManager.model.panes.right.activeSurfaceId)
            .toBe(APP.id);
    });

    it('keeps a root view where the user moved it when more output arrives', () => {
        const { result } = renderHook(useHarness, { wrapper });
        const browserId = 'conversation-execution:conversation-1:root:browser';

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => result.current.windowManager.commands.moveSurface(
            browserId,
            DESKTOP_PANE_IDS.LEFT,
        ));
        act(() => result.current.dispatchEffect(rootViewEffect('browser', 'root-2')));

        expect(result.current.windowManager.model.panes.left.surfaceIds)
            .toEqual([CHAT.id, browserId]);
        expect(result.current.windowManager.model.panes.right.surfaceIds)
            .not.toContain(browserId);
    });

    it('keeps an explicitly closed root view closed during the same conversation', () => {
        const { result } = renderHook(useHarness, { wrapper });
        const browserId = 'conversation-execution:conversation-1:root:browser';

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => result.current.controller.closeExecutionSurface(
            result.current.windowManager.model.surfacesById[browserId],
        ));
        act(() => result.current.dispatchEffect(rootViewEffect('browser', 'root-2')));

        expect(result.current.windowManager.model.surfacesById[browserId])
            .toBeUndefined();
    });

    it('opens a sub-agent view only through the explicit command', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => {
            result.current.dispatchAgent({
                type: 'AGENT_STARTED',
                agentId: 'root-1',
                agentName: 'root',
                parentAgentId: null,
                instruction: '',
                timestamp: 1,
            });
            result.current.dispatchAgent({
                type: 'AGENT_STARTED',
                agentId: 'researcher-1',
                agentName: 'researcher',
                parentAgentId: 'root-1',
                instruction: '',
                timestamp: 2,
            });
        });

        expect(result.current.windowManager.model.surfaces)
            .toHaveLength(1);

        act(() => result.current.controller.openAgentView(
            'researcher-1',
            'terminal',
        ));

        const terminalId =
            'conversation-execution:conversation-1:researcher-1:terminal';
        expect(result.current.windowManager.model.panes.right.activeSurfaceId)
            .toBe(terminalId);
        expect(result.current.windowManager.model.surfacesById[terminalId].label)
            .toBe('Researcher · Terminal');
    });

    it('closes only conversation execution views on a conversation switch', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => {
            result.current.windowManager.commands.openSurface(
                APP,
                DESKTOP_PANE_IDS.RIGHT,
            );
            result.current.windowManager.commands.openSurface(
                ARTIFACT,
                DESKTOP_PANE_IDS.RIGHT,
            );
        });
        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => result.current.dispatchEffect({
            type: APP_EFFECT_TYPES.CLOSE_CONVERSATION_EXECUTION_VIEWS,
            conversationId: CONVERSATION_ID,
        }));

        expect(result.current.windowManager.model.surfacesById[APP.id])
            .toEqual(APP);
        expect(result.current.windowManager.model.surfacesById[ARTIFACT.id])
            .toEqual(ARTIFACT);
        expect(result.current.windowManager.model.surfaces.some(
            (surface) => surface.kind === 'conversation-execution',
        )).toBe(false);
    });
});
