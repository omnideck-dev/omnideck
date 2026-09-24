import {
    act,
    renderHook,
} from '@testing-library/react';
import {
    afterEach,
    beforeEach,
    expect,
    it,
    vi,
} from 'vitest';

import useFloatingViewBounds from '../useFloatingViewBounds.js';

let resizeCallback;

beforeEach(() => {
    vi.useFakeTimers();
    resizeCallback = null;
    vi.stubGlobal('ResizeObserver', class ResizeObserver {
        constructor(callback) {
            resizeCallback = callback;
        }

        observe() {}

        disconnect() {}
    });
});

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

it('flushes the last native resize when its observer is torn down', () => {
    const host = document.createElement('div');
    let width = 720;
    let height = 480;
    Object.defineProperties(host, {
        offsetWidth: {
            configurable: true,
            get: () => width,
        },
        offsetHeight: {
            configurable: true,
            get: () => height,
        },
    });
    const updateFloatingBounds = vi.fn();
    const props = {
        viewId: 'view-1',
        floatingView: {
            viewId: 'view-1',
            x: 10,
            y: 20,
            width,
            height,
        },
        fullscreen: false,
        commands: { updateFloatingBounds },
        hostRef: { current: host },
    };
    const { rerender } = renderHook(
        (current) => useFloatingViewBounds(current),
        { initialProps: props },
    );

    width = 860;
    height = 620;
    act(() => resizeCallback());
    expect(updateFloatingBounds).not.toHaveBeenCalled();

    // Docking removes the floating placement and tears down the observer
    // before the 150ms debounce has elapsed.
    rerender({
        ...props,
        floatingView: null,
    });

    expect(updateFloatingBounds).toHaveBeenCalledOnce();
    expect(updateFloatingBounds).toHaveBeenCalledWith('view-1', {
        width: 860,
        height: 620,
    });
});
