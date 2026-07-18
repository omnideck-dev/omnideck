import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import AppsView from '../AppsView.jsx';

const SAMPLE = {
    slug: 'text-lab',
    title: 'Text Lab',
    description: 'Inspect and transform text.',
    icon: 'bi-fonts',
    has_actions: true,
};

beforeEach(() => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ apps: [SAMPLE], home_app_slug: null }),
    }));
});

afterEach(() => vi.restoreAllMocks());

test('lists discovered apps and asks the shell to open one full-space', async () => {
    const onOpenApp = vi.fn();
    render(<AppsView onOpenApp={onOpenApp} />);
    expect(await screen.findByText('Text Lab')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('custom-app-card'));
    expect(onOpenApp).toHaveBeenCalledWith(SAMPLE);
});

test('can open an app directly beside the active chat', async () => {
    const onOpenAppBesideChat = vi.fn();
    render(<AppsView onOpenAppBesideChat={onOpenAppBesideChat} />);

    fireEvent.click(await screen.findByTestId('custom-app-open-split-text-lab'));
    expect(onOpenAppBesideChat).toHaveBeenCalledWith(SAMPLE);
});

test('synchronizes the persisted Home slug with the shell', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ apps: [SAMPLE], home_app_slug: 'text-lab' }),
    }));
    const onHomeAppChange = vi.fn();
    render(<AppsView homeAppSlug={null} onHomeAppChange={onHomeAppChange} />);

    await waitFor(() => expect(onHomeAppChange).toHaveBeenCalledWith('text-lab'));
});
