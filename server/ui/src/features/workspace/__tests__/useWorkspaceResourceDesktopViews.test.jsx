import { useMemo } from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AgentProvider, useAgentDispatch } from '../../agent/AgentState.jsx';
import {
    AppEffectsProvider,
    useAppEffectDispatch,
} from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import {
    createArtifactView,
    createNavigationView,
} from '../../desktop/desktopViews.js';
import useDesktopLayout, {
    DESKTOP_TAB_GROUP_IDS,
} from '../../desktop/useDesktopLayout.jsx';
import useWorkspaceResourceDesktopViews from
    '../useWorkspaceResourceDesktopViews.js';

const CONVERSATION_ID = 'conversation-1';
const CHAT = createNavigationView({
    kind: 'chat',
    conversationId: CONVERSATION_ID,
});
const APP = {
    id: 'custom-app:text-lab',
    type: 'custom-app',
    label: 'Text Lab',
};
const ARTIFACT = createArtifactView({
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
    const desktopLayout = useDesktopLayout({ initialView: CHAT });
    // Exercise the hook through the same generic View command shape exposed to
    // production domain adapters, while retaining the layout for assertions.
    const desktopCommands = useMemo(() => ({
        openView: (view, { tabGroupId, activate = true } = {}) => (
            desktopLayout.commands.openView(
                view,
                tabGroupId,
                { activate },
            )
        ),
        closeView: desktopLayout.commands.closeView,
        closeViews: desktopLayout.commands.closeViews,
        preferredTabGroupId: () => (
            desktopLayout.model.tabGroups.left.viewIds.includes(CHAT.id)
                ? DESKTOP_TAB_GROUP_IDS.RIGHT
                : DESKTOP_TAB_GROUP_IDS.LEFT
        ),
    }), [desktopLayout.commands]);
    useWorkspaceResourceDesktopViews({
        activeConversationId: CONVERSATION_ID,
        desktopModel: desktopLayout.model,
        desktopCommands,
    });
    return {
        desktopLayout,
        dispatchEffect: useAppEffectDispatch(),
        dispatchAgent: useAgentDispatch(),
    };
}

function rootViewEffect(resourceId, agentId = 'root-1') {
    return {
        type: APP_EFFECT_TYPES.ROOT_WORKSPACE_RESOURCE_AVAILABLE,
        conversationId: CONVERSATION_ID,
        agentId,
        agentName: 'root',
        resourceId,
    };
}

describe('useWorkspaceResourceDesktopViews', () => {
    it('adds a root Browser tab opposite Chat without taking focus', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));

        const browserId = 'workspace-resource:conversation-1:root:browser';
        expect(result.current.desktopLayout.model.tabGroups.right.viewIds)
            .toEqual([browserId]);
        expect(result.current.desktopLayout.model.focusedTabGroupId)
            .toBe(DESKTOP_TAB_GROUP_IDS.LEFT);
        expect(result.current.desktopLayout.model.tabGroups.left.activeViewId)
            .toBe(CHAT.id);
    });

    it('does not replace the active tab in the companion tabGroup', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => result.current.desktopLayout.commands.openView(
            APP,
            DESKTOP_TAB_GROUP_IDS.RIGHT,
        ));
        act(() => result.current.dispatchEffect(rootViewEffect('terminal')));

        expect(result.current.desktopLayout.model.tabGroups.right.viewIds)
            .toEqual([
                APP.id,
                'workspace-resource:conversation-1:root:terminal',
            ]);
        expect(result.current.desktopLayout.model.tabGroups.right.activeViewId)
            .toBe(APP.id);
    });

    it('keeps a root view where the user moved it when more output arrives', () => {
        const { result } = renderHook(useHarness, { wrapper });
        const browserId = 'workspace-resource:conversation-1:root:browser';

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => result.current.desktopLayout.commands.moveView(
            browserId,
            DESKTOP_TAB_GROUP_IDS.LEFT,
        ));
        act(() => result.current.dispatchEffect(rootViewEffect('browser', 'root-2')));

        expect(result.current.desktopLayout.model.tabGroups.left.viewIds)
            .toEqual([CHAT.id, browserId]);
        expect(result.current.desktopLayout.model.tabGroups.right.viewIds)
            .not.toContain(browserId);
    });

    it('keeps an explicitly closed root view closed during the same conversation', () => {
        const { result } = renderHook(useHarness, { wrapper });
        const browserId = 'workspace-resource:conversation-1:root:browser';

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => {
            const view = result.current.desktopLayout.model
                .openViewsById[browserId];
            result.current.dispatchEffect({
                type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
                views: [view],
            });
            result.current.desktopLayout.commands.closeView(browserId);
        });
        act(() => result.current.dispatchEffect(rootViewEffect('browser', 'root-2')));

        expect(result.current.desktopLayout.model.openViewsById[browserId])
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

        expect(result.current.desktopLayout.model.openViews)
            .toHaveLength(1);

        act(() => result.current.dispatchEffect({
            type: APP_EFFECT_TYPES.OPEN_AGENT_WORKSPACE_RESOURCE,
            agentId: 'researcher-1',
            resourceId: 'terminal',
        }));

        const terminalId =
            'workspace-resource:conversation-1:researcher-1:terminal';
        expect(result.current.desktopLayout.model.tabGroups.right.activeViewId)
            .toBe(terminalId);
        expect(result.current.desktopLayout.model.openViewsById[terminalId].label)
            .toBe('Researcher · Terminal');
    });

    it('closes only conversation workspace resources on a conversation switch', () => {
        const { result } = renderHook(useHarness, { wrapper });

        act(() => {
            result.current.desktopLayout.commands.openView(
                APP,
                DESKTOP_TAB_GROUP_IDS.RIGHT,
            );
            result.current.desktopLayout.commands.openView(
                ARTIFACT,
                DESKTOP_TAB_GROUP_IDS.RIGHT,
            );
        });
        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => result.current.dispatchEffect({
            type: APP_EFFECT_TYPES.CLOSE_CONVERSATION_WORKSPACE_VIEWS,
            conversationId: CONVERSATION_ID,
        }));

        expect(result.current.desktopLayout.model.openViewsById[APP.id])
            .toEqual(APP);
        expect(result.current.desktopLayout.model.openViewsById[ARTIFACT.id])
            .toEqual(ARTIFACT);
        expect(result.current.desktopLayout.model.openViews.some(
            (view) => view.type === 'workspace-resource',
        )).toBe(false);
    });

    it('treats workspace views in a Conversation close batch as a cascade', () => {
        const { result } = renderHook(useHarness, { wrapper });
        const browserId = 'workspace-resource:conversation-1:root:browser';

        act(() => result.current.dispatchEffect(rootViewEffect('browser')));
        act(() => {
            const browserView = result.current.desktopLayout.model
                .openViewsById[browserId];
            result.current.dispatchEffect({
                type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
                views: [browserView, CHAT],
            });
        });

        expect(result.current.desktopLayout.model.openViewsById[browserId])
            .toBeUndefined();

        // The browser was closed because its Conversation closed, not because
        // the user explicitly dismissed that browser. If the Conversation is
        // still available to this isolated harness, new output may open it
        // again; an incorrectly recorded dismissal would suppress it.
        act(() => result.current.dispatchEffect(
            rootViewEffect('browser', 'root-2'),
        ));
        expect(result.current.desktopLayout.model.openViewsById[browserId])
            .toBeDefined();
    });
});
