import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import AppsView from '../AppsView.jsx';

const SAMPLE = {
    slug: 'text-lab',
    title: 'Text Lab',
    description: 'Inspect and transform text.',
    icon: 'bi-fonts',
    has_actions: true,
};

test('lists discovered apps and asks the shell to open one on the left', () => {
    const onOpenApp = vi.fn();
    render(<AppsView apps={[SAMPLE]} onOpenApp={onOpenApp} />);
    expect(screen.getByText('Text Lab')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Custom Apps/ })).toBeInTheDocument();
    expect(screen.queryByText('text-lab')).not.toBeInTheDocument();
    expect(screen.queryByText('Python')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('custom-app-card'));
    expect(onOpenApp).toHaveBeenCalledWith(SAMPLE);
});

test('asks the catalog owner to refresh', () => {
    const onRefresh = vi.fn();
    render(<AppsView apps={[SAMPLE]} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByTestId('custom-apps-refresh'));
    expect(onRefresh).toHaveBeenCalledOnce();
});

test('keeps the empty state focused on Custom Apps rather than implementation details', () => {
    render(<AppsView />);

    expect(screen.getByText('No Custom Apps yet')).toBeInTheDocument();
    expect(screen.getByText('Ask your Omnideck agent to build one for you.')).toBeInTheDocument();
    expect(screen.queryByText(/folder|omnideck\.json|web\/index|~\/apps/i)).not.toBeInTheDocument();
});
