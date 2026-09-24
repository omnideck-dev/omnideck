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
