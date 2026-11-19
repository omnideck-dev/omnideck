import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SlashHint, { slashOptionId } from '../SlashHint.jsx';

const commands = [{ command: '/goal', description: 'Start a goal' }, { command: '/other', description: 'Something else' }];

describe('SlashHint', () => {
    it('marks only the active option as selected and gives each option an id', () => {
        render(<SlashHint id="hint" commands={commands} activeIndex={1} onPick={vi.fn()} />);
        const options = screen.getAllByRole('option');
        expect(options.map((option) => option.id)).toEqual([slashOptionId('hint', 0), slashOptionId('hint', 1)]);
        expect(options[0]).not.toHaveAttribute('aria-selected');
        expect(options[1]).toHaveAttribute('aria-selected', 'true');
    });

    it('picks the clicked command', () => {
        const onPick = vi.fn();
        render(<SlashHint id="hint" commands={commands} onPick={onPick} />);
        fireEvent.click(screen.getByText('/other'));
        expect(onPick).toHaveBeenCalledWith('/other');
    });
});
