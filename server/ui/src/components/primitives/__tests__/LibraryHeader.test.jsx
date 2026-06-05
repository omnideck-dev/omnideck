import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import LibraryHeader from '../LibraryHeader.jsx';

const VIEWS = [
    { id: 'skills', label: 'My Skills', count: 5 },
    { id: 'categories', label: 'Tool Categories', count: 13 },
];

function setup(overrides = {}) {
    const props = {
        views: VIEWS,
        activeView: 'skills',
        onViewChange: vi.fn(),
        searchValue: '',
        onSearchChange: vi.fn(),
        searchPlaceholder: 'Search skills',
        ...overrides,
    };
    return { props, ...render(<LibraryHeader {...props} />) };
}

describe('LibraryHeader', () => {
    it('renders a tab per view with its count', () => {
        setup();
        expect(screen.getByRole('tab', { name: /My Skills/ })).toHaveTextContent('5');
        expect(screen.getByRole('tab', { name: /Tool Categories/ })).toHaveTextContent('13');
    });

    it('marks the active view tab selected', () => {
        setup({ activeView: 'categories' });
        expect(screen.getByRole('tab', { name: /Tool Categories/ })).toHaveAttribute('aria-selected', 'true');
        expect(screen.getByRole('tab', { name: /My Skills/ })).toHaveAttribute('aria-selected', 'false');
    });

    it('calls onViewChange when a tab is clicked', () => {
        const { props } = setup();
        fireEvent.click(screen.getByRole('tab', { name: /Tool Categories/ }));
        expect(props.onViewChange).toHaveBeenCalledWith('categories');
    });

    it('shows the search placeholder for the active view', () => {
        setup({ searchPlaceholder: 'Search tool categories' });
        expect(screen.getByPlaceholderText('Search tool categories')).toBeInTheDocument();
    });

    it('calls onSearchChange as the user types', () => {
        const { props } = setup();
        fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'mail' } });
        expect(props.onSearchChange).toHaveBeenCalledWith('mail');
    });

    it('renders right-aligned actions when provided', () => {
        setup({ actions: <button type="button">+ New</button> });
        expect(screen.getByRole('button', { name: '+ New' })).toBeInTheDocument();
    });
});
