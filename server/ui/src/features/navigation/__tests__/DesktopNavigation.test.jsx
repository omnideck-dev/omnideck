import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const session = vi.hoisted(() => ({
    activeConversationId: 'conversation-1',
    loadConversation: vi.fn(),
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useConversationSessionState: () => ({
        activeConversationId: session.activeConversationId,
    }),
    useConversationSessionCommands: () => ({
        loadConversation: session.loadConversation,
    }),
}));

const {
    DesktopNavigationProvider,
    useDesktopNavigation,
} = await import('../DesktopNavigation.jsx');

function wrapper({ children }) {
    return <DesktopNavigationProvider>{children}</DesktopNavigationProvider>;
}

describe('DesktopNavigationProvider', () => {
    beforeEach(() => {
        session.activeConversationId = 'conversation-1';
        session.loadConversation.mockReset();
        session.loadConversation.mockResolvedValue(true);
    });

    it('stores serializable destinations with stable IDs', () => {
        const { result } = renderHook(useDesktopNavigation, { wrapper });

        act(() => result.current.openAgent('agent-2'));
        expect(result.current.destination).toEqual({
            kind: 'network',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
        });

        act(() => result.current.openRoutines('routine-2', 'run-3'));
        expect(result.current.destination).toEqual({
            kind: 'routines',
            routineId: 'routine-2',
            runId: 'run-3',
        });
    });

    it('can restore a serializable destination owned by a desktop surface', () => {
        const { result } = renderHook(useDesktopNavigation, { wrapper });
        const destination = { kind: 'settings', tab: 'skills' };

        act(() => result.current.openDestination(destination));

        expect(result.current.destination).toEqual(destination);
    });

    it('opens the active conversation without reloading it', async () => {
        const { result } = renderHook(useDesktopNavigation, { wrapper });
        const initialDestination = result.current.destination;

        await act(async () => result.current.openConversation('conversation-1'));

        expect(session.loadConversation).not.toHaveBeenCalled();
        expect(result.current.destination).not.toBe(initialDestination);
        expect(result.current.destination).toEqual({
            kind: 'chat',
            conversationId: 'conversation-1',
        });
    });

    it('loads a different conversation before navigating to it', async () => {
        const { result } = renderHook(useDesktopNavigation, { wrapper });

        await act(async () => result.current.openConversation('conversation-2'));

        expect(session.loadConversation).toHaveBeenCalledWith('conversation-2');
        expect(result.current.destination).toEqual({
            kind: 'chat',
            conversationId: 'conversation-2',
        });
    });

    it('carries an artifact as serializable conversation navigation intent', async () => {
        const { result } = renderHook(useDesktopNavigation, { wrapper });

        await act(async () => result.current.openConversation('conversation-2', {
            artifactId: 'artifact-3',
        }));

        expect(result.current.destination).toEqual({
            kind: 'chat',
            conversationId: 'conversation-2',
            artifactId: 'artifact-3',
        });
    });

    it('keeps the current destination when conversation loading fails', async () => {
        session.loadConversation.mockResolvedValue(false);
        const { result } = renderHook(useDesktopNavigation, { wrapper });
        act(() => result.current.openApps());

        await act(async () => result.current.openConversation('missing'));

        expect(result.current.destination).toEqual({ kind: 'apps' });
    });
});
