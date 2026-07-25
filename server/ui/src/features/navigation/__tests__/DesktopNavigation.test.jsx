import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const session = vi.hoisted(() => ({
    activeConversationId: 'conversation-1',
    loadConversation: vi.fn(),
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: () => session.activeConversationId,
    useConversationSessionState: () => ({
        activeConversationId: session.activeConversationId,
    }),
    useConversationSessionCommands: () => ({
        loadConversation: session.loadConversation,
    }),
}));

const {
    DesktopNavigationProvider,
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} = await import('../DesktopNavigation.jsx');

function wrapper({ children }) {
    return <DesktopNavigationProvider>{children}</DesktopNavigationProvider>;
}

function useNavigationHarness() {
    return {
        ...useDesktopNavigationState(),
        ...useDesktopNavigationCommands(),
    };
}

describe('DesktopNavigationProvider', () => {
    beforeEach(() => {
        session.activeConversationId = 'conversation-1';
        session.loadConversation.mockReset();
        session.loadConversation.mockResolvedValue(true);
    });

    it('stores serializable navigationTargets with stable IDs', () => {
        const { result } = renderHook(useNavigationHarness, { wrapper });

        act(() => result.current.openAgent('agent-2'));
        expect(result.current.navigationTarget).toEqual({
            kind: 'network',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
        });

        act(() => result.current.openRoutines('routine-2', 'run-3'));
        expect(result.current.navigationTarget).toEqual({
            kind: 'routines',
            routineId: 'routine-2',
            runId: 'run-3',
        });
    });

    it('can restore a serializable navigation target owned by a Desktop View', () => {
        const { result } = renderHook(useNavigationHarness, { wrapper });
        const navigationTarget = { kind: 'settings', tab: 'skills' };

        act(() => result.current.openTarget(navigationTarget));

        expect(result.current.navigationTarget).toEqual(navigationTarget);
    });

    it('opens the active conversation without reloading it', async () => {
        const { result } = renderHook(useNavigationHarness, { wrapper });
        const initialNavigationTarget = result.current.navigationTarget;

        await act(async () => result.current.openConversation('conversation-1'));

        expect(session.loadConversation).not.toHaveBeenCalled();
        expect(result.current.navigationTarget).not.toBe(initialNavigationTarget);
        expect(result.current.navigationTarget).toEqual({
            kind: 'chat',
            conversationId: 'conversation-1',
        });
    });

    it('loads a different conversation before navigating to it', async () => {
        const { result } = renderHook(useNavigationHarness, { wrapper });

        await act(async () => result.current.openConversation('conversation-2'));

        expect(session.loadConversation).toHaveBeenCalledWith('conversation-2');
        expect(result.current.navigationTarget).toEqual({
            kind: 'chat',
            conversationId: 'conversation-2',
        });
    });

    it('carries an artifact as serializable conversation navigation intent', async () => {
        const { result } = renderHook(useNavigationHarness, { wrapper });

        await act(async () => result.current.openConversation('conversation-2', {
            artifactId: 'artifact-3',
        }));

        expect(result.current.navigationTarget).toEqual({
            kind: 'chat',
            conversationId: 'conversation-2',
            artifactId: 'artifact-3',
        });
    });

    it('keeps the current navigationTarget when conversation loading fails', async () => {
        session.loadConversation.mockResolvedValue(false);
        const { result } = renderHook(useNavigationHarness, { wrapper });
        act(() => result.current.openApps());

        await act(async () => result.current.openConversation('missing'));

        expect(result.current.navigationTarget).toEqual({ kind: 'apps' });
    });
});
