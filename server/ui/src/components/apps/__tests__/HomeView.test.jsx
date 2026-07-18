import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import HomeView from '../HomeView.jsx';

const SAMPLE = {
    slug: 'text-lab',
    title: 'Text Lab',
    description: 'Inspect and transform text.',
    icon: 'bi-fonts',
    has_actions: true,
    editable: false,
};

beforeEach(() => {
    global.fetch = vi.fn((url, options = {}) => {
        if (url === '/api/folder-apps' && !options.method) {
            return Promise.resolve({ ok: true, json: async () => ({ apps: [SAMPLE] }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true, home_app_slug: null }) });
    });
});

afterEach(() => vi.restoreAllMocks());

test('resolves the configured app into the shell-level Home workspace', async () => {
    const onOpenApp = vi.fn();
    render(
        <HomeView
            slug="text-lab"
            onOpenApps={vi.fn()}
            onHomeAppChange={vi.fn()}
            onOpenApp={onOpenApp}
        />,
    );

    await waitFor(() => expect(onOpenApp).toHaveBeenCalledWith(SAMPLE));
});

test('recovers when the configured Home app no longer exists', async () => {
    global.fetch = vi.fn((url, options = {}) => {
        if (url === '/api/folder-apps' && !options.method) {
            return Promise.resolve({ ok: true, json: async () => ({ apps: [] }) });
        }
        return Promise.resolve({ ok: true, json: async () => ({ ok: true, home_app_slug: null }) });
    });
    const onHomeAppChange = vi.fn();
    const onOpenApps = vi.fn();
    render(
        <HomeView
            slug="missing"
            onOpenApps={onOpenApps}
            onHomeAppChange={onHomeAppChange}
            onOpenApp={vi.fn()}
        />,
    );

    fireEvent.click(await screen.findByText('Use Chat as Home'));
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(
        '/api/folder-apps/home', { method: 'DELETE' },
    ));
    expect(onHomeAppChange).toHaveBeenCalledWith(null);
    expect(onOpenApps).toHaveBeenCalledOnce();
});
