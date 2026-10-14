import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';
import useIsMobileViewport from '../useIsMobileViewport.js';

// A minimal MediaQueryList stand-in that lets tests fire a 'change' event.
function createMatchMediaMock(initialMatches) {
    let matches = initialMatches;
    let changeHandler = null;
    const mql = {
        get matches() { return matches; },
        addEventListener: vi.fn((event, handler) => {
            if (event === 'change') changeHandler = handler;
        }),
        removeEventListener: vi.fn((event, handler) => {
            if (event === 'change' && changeHandler === handler) changeHandler = null;
        }),
    };
    return {
        mql,
        matchMedia: vi.fn(() => mql),
        setMatches(next) {
            matches = next;
            changeHandler?.({ matches: next });
        },
    };
}

let latest;
function Harness() {
    latest = useIsMobileViewport();
    return null;
}

afterEach(() => {
    latest = undefined;
    vi.restoreAllMocks();
});

describe('useIsMobileViewport', () => {
    it('reflects the initial match state', () => {
        const { matchMedia } = createMatchMediaMock(true);
        window.matchMedia = matchMedia;
        render(<Harness />);
        expect(latest).toBe(true);
    });

    it('updates when the media query match changes', () => {
        const { matchMedia, setMatches } = createMatchMediaMock(false);
        window.matchMedia = matchMedia;
        render(<Harness />);
        expect(latest).toBe(false);
        act(() => setMatches(true));
        expect(latest).toBe(true);
    });

    it('reflects a match that changes in the gap between mount and subscribing', () => {
        // A plain useState initializer + useEffect subscription can miss a
        // change that lands between the initial render (which captures the
        // starting value) and the later effect attaching its 'change'
        // listener - only a subsequent event would be seen. Simulate that
        // gap by flipping the match as a side effect of subscribing itself,
        // with no 'change' event ever dispatched, and confirm the hook
        // still reflects it (useSyncExternalStore re-checks on subscribe).
        let matches = false;
        const mql = {
            get matches() { return matches; },
            addEventListener: vi.fn((event) => {
                if (event === 'change') matches = true;
            }),
            removeEventListener: vi.fn(),
        };
        window.matchMedia = vi.fn(() => mql);
        render(<Harness />);
        expect(latest).toBe(true);
    });

    it('unsubscribes on unmount', () => {
        const { matchMedia, mql } = createMatchMediaMock(false);
        window.matchMedia = matchMedia;
        const { unmount } = render(<Harness />);
        unmount();
        expect(mql.removeEventListener).toHaveBeenCalledWith(
            'change',
            mql.addEventListener.mock.calls[0][1],
        );
    });
});
