import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import IconPickerPopover from '../IconPickerPopover.jsx';

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('IconPickerPopover', () => {
    it('positions from a virtual anchor without observing it as a DOM element', () => {
        const observe = vi.fn((target) => {
            if (!(target instanceof Element)) throw new TypeError('ResizeObserver target must be an Element');
        });
        vi.stubGlobal('ResizeObserver', class ResizeObserver {
            observe = observe;

            disconnect() {}
        });

        render(
            <IconPickerPopover
                anchorRect={{
                    left: 20,
                    right: 52,
                    top: 20,
                    bottom: 52,
                    width: 32,
                    height: 32,
                }}
                icons={['bi-folder', 'bi-briefcase']}
                current="bi-folder"
                onPick={vi.fn()}
                onClose={vi.fn()}
                testId="icon-picker"
            />,
        );

        expect(screen.getByTestId('icon-picker')).toBeVisible();
        expect(observe).not.toHaveBeenCalled();
    });
});
