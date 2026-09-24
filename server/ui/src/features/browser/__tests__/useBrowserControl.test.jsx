import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import useBrowserControl from '../useBrowserControl.js';

class FakeWebSocket {
    static OPEN = 1;

    static instances = [];

    constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.send = vi.fn();
        FakeWebSocket.instances.push(this);
    }

    close() {
        this.readyState = 3;
        this.onclose?.();
    }
}

describe('useBrowserControl', () => {
    beforeEach(() => {
        FakeWebSocket.instances = [];
        vi.stubGlobal('WebSocket', FakeWebSocket);
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('allows takeover only while the control channel is connected', () => {
        const { result } = renderHook(() => useBrowserControl({
            target: { type: 'conversation', conversationId: 'conversation-1' },
            selectedTabId: 1,
            canControl: true,
            enabled: true,
        }));
        const socket = FakeWebSocket.instances[0];

        expect(result.current.canControl).toBe(false);

        act(() => {
            socket.readyState = FakeWebSocket.OPEN;
            socket.onopen();
        });

        expect(result.current.connected).toBe(true);
        expect(result.current.canControl).toBe(true);
    });

    it('surfaces a rejected root-browser session and revokes takeover', () => {
        const { result } = renderHook(() => useBrowserControl({
            target: { type: 'conversation', conversationId: 'conversation-1' },
            selectedTabId: 1,
            canControl: true,
            enabled: true,
        }));
        const socket = FakeWebSocket.instances[0];

        act(() => {
            socket.readyState = FakeWebSocket.OPEN;
            socket.onopen();
            socket.onmessage({
                data: JSON.stringify({
                    type: 'error',
                    reason: 'no_active_browser',
                }),
            });
        });

        expect(result.current.error).toBe('no_active_browser');
        expect(result.current.canControl).toBe(false);
        expect(result.current.engaged).toBe(false);
    });

    it('reconnects when an established conversation Browser is replaced', () => {
        vi.useFakeTimers();
        renderHook(() => useBrowserControl({
            target: { type: 'conversation', conversationId: 'conversation-1' },
            selectedTabId: 1,
            canControl: true,
            enabled: true,
        }));
        const socket = FakeWebSocket.instances[0];

        act(() => {
            socket.readyState = FakeWebSocket.OPEN;
            socket.onopen();
            socket.onmessage({ data: JSON.stringify({ type: 'tabs', tabs: [] }) });
            socket.readyState = 3;
            socket.onclose();
            vi.advanceTimersByTime(250);
        });

        expect(FakeWebSocket.instances).toHaveLength(2);
        expect(FakeWebSocket.instances[1].url).toContain('conversation_id=conversation-1');
    });

    it('reconnects when the root-agent Browser session identity changes', () => {
        const { rerender } = renderHook(
            ({ sessionKey }) => useBrowserControl({
                target: { type: 'conversation', conversationId: 'conversation-1' },
                selectedTabId: 1,
                canControl: true,
                enabled: true,
                sessionKey,
            }),
            { initialProps: { sessionKey: 'root-agent-1' } },
        );
        const firstSocket = FakeWebSocket.instances[0];

        rerender({ sessionKey: 'root-agent-2' });

        expect(firstSocket.readyState).toBe(3);
        expect(FakeWebSocket.instances).toHaveLength(2);
    });

    it('opens a user-scoped Browser without a conversation', () => {
        const { result } = renderHook(() => useBrowserControl({
            target: { type: 'user' },
            selectedTabId: 1,
            canControl: true,
            enabled: true,
            alwaysEngaged: true,
        }));
        const socket = FakeWebSocket.instances[0];

        expect(socket.url).toContain('scope=user');

        act(() => {
            socket.readyState = FakeWebSocket.OPEN;
            socket.onopen();
        });

        expect(result.current.engaged).toBe(true);
        expect(result.current.toggleEngage).toBeNull();
    });
});
