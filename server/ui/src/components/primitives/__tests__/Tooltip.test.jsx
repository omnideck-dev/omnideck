import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import Tooltip from '../Tooltip.jsx';

describe('Tooltip', () => {
    it('positions from the wrapped element, not its display:contents wrapper', () => {
        render(
            <Tooltip text="Explains things" placement="top">
                <div data-testid="target">Target</div>
            </Tooltip>,
        );
        const target = screen.getByTestId('target');
        vi.spyOn(target, 'getBoundingClientRect').mockReturnValue({
            left: 100, top: 200, right: 140, bottom: 220, width: 40, height: 20,
        });

        fireEvent.mouseEnter(target);

        const tip = screen.getByText('Explains things');
        expect(tip.style.left).toBe('120px');
        expect(tip.style.top).toBe('192px');
    });

    it('renders children alone when there is no text', () => {
        render(<Tooltip text=""><span>Plain</span></Tooltip>);
        fireEvent.mouseEnter(screen.getByText('Plain'));
        expect(document.body.textContent).toBe('Plain');
    });
});
