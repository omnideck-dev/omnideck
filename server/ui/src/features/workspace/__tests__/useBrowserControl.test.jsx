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
        vi.unstubAllGlobals();
    });

    it('allows takeover only while the control channel is connected', () => {
        const { result } = renderHook(() => useBrowserControl({
            conversationId: 'conversation-1',
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
            conversationId: 'conversation-1',
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
});
