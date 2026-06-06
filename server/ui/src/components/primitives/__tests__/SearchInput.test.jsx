import { fireEvent, render, screen } from '@testing-library/react';
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
});
