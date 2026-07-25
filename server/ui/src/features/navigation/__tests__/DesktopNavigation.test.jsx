import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';

const session = vi.hoisted(() => ({
    activeConversationId: 'conversation-1',
    loadConversation: vi.fn(),
}));
const desktop = vi.hoisted(() => ({
    focusedViewId: 'destination:conversation',
    catalog: {
        openViewsById: {
            'destination:conversation': {
                id: 'destination:conversation',
                identity: {
                    navigationTarget: {
                        kind: 'chat',
                        conversationId: 'conversation-1',
                    },
                },
            },
        },
    },
    commands: {
        openView: vi.fn(),
    },
}));
const dispatchAppEffect = vi.hoisted(() => vi.fn());

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: () => session.activeConversationId,
    useConversationSessionCommands: () => ({
        loadConversation: session.loadConversation,
    }),
}));

vi.mock('../../desktop/DesktopViewRuntime.jsx', () => ({
    useDesktopViewCommands: () => desktop.commands,
    useDesktopViewCatalog: () => desktop.catalog,
    useFocusedViewId: () => desktop.focusedViewId,
}));

vi.mock('../../app/AppEffects.jsx', () => ({
    useAppEffectDispatch: () => dispatchAppEffect,
}));

const {
    DesktopNavigationProvider,
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
} = await import('../DesktopNavigation.jsx');

function wrapper({ children }) {
    return (
        <DesktopNavigationProvider>
            {children}
        </DesktopNavigationProvider>
    );
}

describe('DesktopNavigationProvider', () => {
    beforeEach(() => {
        session.activeConversationId = 'conversation-1';
        session.loadConversation.mockReset();
        session.loadConversation.mockResolvedValue(true);
        desktop.commands.openView.mockReset();
        dispatchAppEffect.mockReset();
    });

    it('translates named navigation into one Desktop View write path', () => {
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        act(() => result.current.openAgent('agent-2'));
        expect(desktop.commands.openView).toHaveBeenLastCalledWith(
            expect.objectContaining({
                id: 'destination:conversation',
                identity: {
                    navigationTarget: {
                        kind: 'network',
                        conversationId: 'conversation-1',
                        agentId: 'agent-2',
                    },
                },
            }),
            { tabGroupId: 'left' },
        );

        act(() => result.current.openRoutines('routine-2', 'run-3'));
        expect(desktop.commands.openView).toHaveBeenLastCalledWith(
            expect.objectContaining({
                id: 'destination:routines',
                identity: {
                    navigationTarget: {
                        kind: 'routines',
                        routineId: 'routine-2',
                        runId: 'run-3',
                    },
                },
            }),
            { tabGroupId: 'left' },
        );
    });

    it('derives current location from the focused View', () => {
        const { result } = renderHook(useCurrentNavigationTarget);

        expect(result.current).toEqual({
            kind: 'chat',
            conversationId: 'conversation-1',
        });
    });

    it('loads a different conversation before opening its View', async () => {
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        await act(async () => result.current.openConversation(
            'conversation-2',
        ));

        expect(session.loadConversation)
            .toHaveBeenCalledWith('conversation-2');
        expect(desktop.commands.openView).toHaveBeenCalledWith(
            expect.objectContaining({
                identity: {
                    navigationTarget: {
                        kind: 'chat',
                        conversationId: 'conversation-2',
                    },
                },
            }),
            { tabGroupId: 'left' },
        );
    });

    it('opens the active conversation without reloading it', async () => {
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        await act(async () => result.current.openConversation(
            'conversation-1',
        ));

        expect(session.loadConversation).not.toHaveBeenCalled();
        expect(desktop.commands.openView).toHaveBeenCalledOnce();
    });

    it('hands an artifact deep link to the Artifact domain after loading', async () => {
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        await act(async () => result.current.openConversation(
            'conversation-2',
            { artifactId: 'artifact-3' },
        ));

        expect(desktop.commands.openView).toHaveBeenCalledWith(
            expect.objectContaining({
                identity: {
                    navigationTarget: {
                        kind: 'chat',
                        conversationId: 'conversation-2',
                    },
                },
            }),
            { tabGroupId: 'left' },
        );
        expect(dispatchAppEffect).toHaveBeenCalledWith({
            type: APP_EFFECT_TYPES.OPEN_ARTIFACT_REQUESTED,
            artifactId: 'artifact-3',
            conversationId: 'conversation-2',
        });
    });

    it('hands an unresolved Custom App slug to its domain owner', () => {
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        act(() => result.current.openCustomApp('text-lab'));

        expect(desktop.commands.openView).not.toHaveBeenCalled();
        expect(dispatchAppEffect).toHaveBeenCalledWith({
            type: APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED,
            appSlug: 'text-lab',
        });
    });

    it('does not change Desktop when conversation loading fails', async () => {
        session.loadConversation.mockResolvedValue(false);
        const { result } = renderHook(
            useDesktopNavigationCommands,
            { wrapper },
        );

        await act(async () => result.current.openConversation('missing'));

        expect(desktop.commands.openView).not.toHaveBeenCalled();
        expect(dispatchAppEffect).not.toHaveBeenCalled();
    });
});
