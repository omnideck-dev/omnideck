import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import Popover from '../Popover.jsx';

function Harness({ anchorRect, flipThreshold, onOption = vi.fn() }) {
    const [open, setOpen] = useState(false);
    const triggerRef = useRef(null);

    return (
        <div data-testid="clipping-pane" style={{ overflow: 'hidden' }}>
            <button
                ref={(node) => {
                    triggerRef.current = node;
                    if (node) node.getBoundingClientRect = () => anchorRect;
                }}
                type="button"
                onClick={() => setOpen((value) => !value)}
                data-testid="trigger"
            >
                Open
            </button>
            {open && (
                <Popover
                    anchorRef={triggerRef}
                    onClose={() => setOpen(false)}
                    align="end"
                    width={380}
                    maxHeight={340}
                    flipThreshold={flipThreshold}
                    role="dialog"
                    ariaLabel="Options"
                    testId="popover"
                >
                    <button type="button" onClick={onOption}>Option</button>
                </Popover>
            )}
        </div>
    );
}

const originalInnerWidth = window.innerWidth;
const originalInnerHeight = window.innerHeight;

afterEach(() => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalInnerWidth });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalInnerHeight });
});

describe('Popover', () => {
    it('portals outside a clipping pane and flips above a low trigger', async () => {
        const user = userEvent.setup();
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 880 });
        Object.defineProperty(window, 'innerHeight', { configurable: true, value: 620 });
        const rect = {
            left: 715,
            right: 808,
            top: 363,
            bottom: 391,
            width: 93,
            height: 28,
        };
        render(<Harness anchorRect={rect} />);

        await user.click(screen.getByTestId('trigger'));
        const popover = screen.getByTestId('popover');

        expect(popover.parentElement).toBe(document.body);
        expect(popover).toHaveAttribute('data-placement', 'top');
        expect(popover).toHaveStyle({
            bottom: '263px',
            left: '428px',
            maxHeight: '340px',
            width: '380px',
        });
    });

    it('flips horizontal alignment instead of covering adjacent UI', async () => {
        const user = userEvent.setup();
        Object.defineProperty(window, 'innerWidth', { configurable: true, value: 880 });
        Object.defineProperty(window, 'innerHeight', { configurable: true, value: 620 });
        const rect = {
            left: 289,
            right: 380,
            top: 363,
            bottom: 391,
            width: 91,
            height: 28,
        };
        render(<Harness anchorRect={rect} flipThreshold={160} />);

        await user.click(screen.getByTestId('trigger'));

        const popover = screen.getByTestId('popover');
        expect(popover).toHaveAttribute('data-placement', 'bottom');
        expect(popover).toHaveStyle({
            left: '289px',
            maxHeight: '215px',
            top: '397px',
            width: '380px',
        });
    });

    it('keeps portaled content interactive and closes outside or on Escape', async () => {
        const user = userEvent.setup();
        const onOption = vi.fn();
        const rect = {
            left: 20,
            right: 120,
            top: 20,
            bottom: 50,
            width: 100,
            height: 30,
        };
        render(<Harness anchorRect={rect} onOption={onOption} />);

        await user.click(screen.getByTestId('trigger'));
        await user.click(screen.getByRole('button', { name: 'Option' }));
        expect(onOption).toHaveBeenCalledOnce();
        expect(screen.getByTestId('popover')).toBeInTheDocument();

        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('popover')).not.toBeInTheDocument();
        expect(screen.getByTestId('trigger')).toHaveFocus();

        await user.click(screen.getByTestId('trigger'));
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('popover')).not.toBeInTheDocument();
    });
});
