import { render, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { useRef } from 'react';
import useIframeScrollPreservation from '../useIframeScrollPreservation.js';

// Fakes the parts of an iframe's contentWindow this hook touches. Real jsdom
// iframes don't implement scroll layout, so a plain fake stands in for one.
function makeFakeWindow() {
    return {
        scrollX: 0,
        scrollY: 0,
        scrollTo: vi.fn(function scrollTo(x, y) {
            this.scrollX = x;
            this.scrollY = y;
        }),
        addEventListener: vi.fn(),
    };
}

// Captures the hook's return value and exposes a ref the test can point at a
// fake contentWindow, mirroring how FileContentRenderer wires up an iframe.
let latest;
function Harness({ resetKey }) {
    const iframeRef = useRef({ contentWindow: makeFakeWindow() });
    latest = { handleLoad: useIframeScrollPreservation(iframeRef, resetKey), iframeRef };
    return null;
}

describe('useIframeScrollPreservation', () => {
    it('restores the last scroll position after a reload', () => {
        render(<Harness resetKey="file.html" />);
        const win = latest.iframeRef.current.contentWindow;

        // Simulate the reader scrolling, then a reload firing onLoad.
        act(() => { latest.handleLoad(); });
        const scrollHandler = win.addEventListener.mock.calls.find(([evt]) => evt === 'scroll')[1];
        act(() => { win.scrollX = 40; win.scrollY = 300; scrollHandler(); });

        act(() => { latest.handleLoad(); });
        expect(win.scrollTo).toHaveBeenLastCalledWith(40, 300);
    });

    it('resets to the top when the previewed file changes', () => {
        const { rerender } = render(<Harness resetKey="file.html" />);
        const win = latest.iframeRef.current.contentWindow;

        act(() => { latest.handleLoad(); });
        const scrollHandler = win.addEventListener.mock.calls.find(([evt]) => evt === 'scroll')[1];
        act(() => { win.scrollX = 40; win.scrollY = 300; scrollHandler(); });

        // Same iframe ref, but the previewed file identity changes.
        rerender(<Harness resetKey="other-file.html" />);
        act(() => { latest.handleLoad(); });
        expect(win.scrollTo).toHaveBeenLastCalledWith(0, 0);
    });

    it('does nothing when the iframe has no contentWindow yet', () => {
        function EmptyHarness() {
            const iframeRef = useRef(null);
            latest = { handleLoad: useIframeScrollPreservation(iframeRef, 'file.html') };
            return null;
        }
        render(<EmptyHarness />);
        expect(() => act(() => { latest.handleLoad(); })).not.toThrow();
    });
});
