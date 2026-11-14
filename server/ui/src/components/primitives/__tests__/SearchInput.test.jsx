import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import SearchInput from '../SearchInput.jsx';

describe('SearchInput', () => {
    it('renders the placeholder and is a searchbox', () => {
        render(<SearchInput value="" onChange={() => {}} placeholder="Search skills…" />);
        expect(screen.getByPlaceholderText('Search skills…')).toBeInTheDocument();
        expect(screen.getByRole('searchbox')).toBeInTheDocument();
    });

    it('reports typed text through onChange', () => {
        const onChange = vi.fn();
        render(<SearchInput value="" onChange={onChange} placeholder="Search" />);
        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mail' } });
        expect(onChange).toHaveBeenCalledWith('mail');
    });

    it('shows a clear button only when there is a value, and clears to empty', () => {
        const onChange = vi.fn();
        const { rerender } = render(<SearchInput value="" onChange={onChange} testId="s" clearTestId="s-clear" />);
        expect(screen.queryByTestId('s-clear')).not.toBeInTheDocument();

        rerender(<SearchInput value="mail" onChange={onChange} testId="s" clearTestId="s-clear" />);
        fireEvent.click(screen.getByTestId('s-clear'));
        expect(onChange).toHaveBeenCalledWith('');
    });

    it('omits the clear button when clearable is false', () => {
        render(<SearchInput value="mail" onChange={() => {}} clearable={false} clearTestId="s-clear" />);
        expect(screen.queryByTestId('s-clear')).not.toBeInTheDocument();
    });

    it('disables editing and clearing together', () => {
        render(
            <SearchInput
                value="mail"
                onChange={() => {}}
                disabled
                clearTestId="s-clear"
            />,
        );
        expect(screen.getByRole('searchbox')).toBeDisabled();
        expect(screen.queryByTestId('s-clear')).not.toBeInTheDocument();
    });
    describe('filters', () => {
        const FILTERS = [
            { id: 'goals', label: 'With a goal', chip: 'Goals', icon: 'bi-bullseye', count: 3 },
            { id: 'running', label: 'Running now', icon: 'bi-arrow-repeat', count: 1 },
        ];

        it('has no filter button without filters', () => {
            render(<SearchInput value="" onChange={() => {}} />);
            expect(screen.queryByRole('button', { name: 'Filter' })).not.toBeInTheDocument();
        });

        it('picks a filter from the menu and closes it', async () => {
            const user = userEvent.setup();
            const onFilterChange = vi.fn();
            render(<SearchInput value="" onChange={() => {}} filters={FILTERS} filter={null} onFilterChange={onFilterChange} />);
            await user.click(screen.getByRole('button', { name: 'Filter' }));
            expect(screen.getByRole('menuitemradio', { name: 'All' })).toHaveAttribute('aria-checked', 'true');
            expect(screen.getByRole('menuitemradio', { name: /With a goal/ })).toHaveTextContent('3');
            await user.click(screen.getByRole('menuitemradio', { name: /Running now/ }));
            expect(onFilterChange).toHaveBeenCalledWith('running');
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
        });

        it('shows the chosen filter as a chip that clears it', async () => {
            const user = userEvent.setup();
            const onFilterChange = vi.fn();
            render(<SearchInput value="" onChange={() => {}} placeholder="Search conversations…" filters={FILTERS} filter="goals" onFilterChange={onFilterChange} filterTestId="f" />);
            expect(screen.getByTestId('f-chip')).toHaveTextContent('Goals');
            expect(screen.getByRole('searchbox')).toHaveAttribute('placeholder', 'Search…');
            await user.click(screen.getByRole('button', { name: 'Clear Goals filter' }));
            expect(onFilterChange).toHaveBeenCalledWith(null);
        });

        it('moves through options with the arrow keys and closes on Escape', async () => {
            const user = userEvent.setup();
            render(<SearchInput value="" onChange={() => {}} filters={FILTERS} filter="goals" onFilterChange={() => {}} />);
            const trigger = screen.getByRole('button', { name: 'Filter' });
            await user.click(trigger);
            expect(screen.getByRole('menuitemradio', { name: /With a goal/ })).toHaveFocus();
            await user.keyboard('{ArrowDown}');
            expect(screen.getByRole('menuitemradio', { name: /Running now/ })).toHaveFocus();
            await user.keyboard('{ArrowDown}');
            expect(screen.getByRole('menuitemradio', { name: 'All' })).toHaveFocus();
            await user.keyboard('{Escape}');
            expect(screen.queryByRole('menu')).not.toBeInTheDocument();
            expect(trigger).toHaveFocus();
        });
    });
});
