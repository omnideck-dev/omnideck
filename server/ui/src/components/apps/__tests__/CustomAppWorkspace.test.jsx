import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import CustomAppWorkspace from '../CustomAppWorkspace.jsx';

const SAMPLE = {
    slug: 'text-lab',
    title: 'Text Lab',
    icon: 'bi-fonts',
};

const baseProps = {
    app: SAMPLE,
    visible: true,
    origin: 'apps',
    homeAppSlug: null,
    tabs: [{ id: 'app:text-lab', testid: 'app:text-lab', label: 'Text Lab', icon: <i /> }],
    activeTab: 'app:text-lab',
    onTabChange: vi.fn(),
    onCloseTab: vi.fn(),
    onOpenChat: vi.fn(),
    onComposeChat: vi.fn(),
    onOpenApps: vi.fn(),
    onHomeAppChange: vi.fn(),
};

beforeEach(() => {
    global.fetch = vi.fn(() => Promise.resolve({ ok: true, json: async () => ({ ok: true }) }));
});

afterEach(() => vi.restoreAllMocks());

test('keeps the same iframe mounted when moving from full-space into a tab', () => {
    const { rerender } = render(<CustomAppWorkspace {...baseProps} layout="full" />);
    const frame = screen.getByTestId('custom-app-frame');
    expect(screen.queryByTestId('preview-tab-bar')).not.toBeInTheDocument();

    rerender(<CustomAppWorkspace {...baseProps} layout="split" />);
    expect(screen.getByTestId('custom-app-frame')).toBe(frame);
    expect(screen.getByTestId('preview-tab-app:text-lab')).toBeInTheDocument();
});

test('opens the current chat and closes globally through trusted shell controls', () => {
    const onOpenChat = vi.fn();
    const onCloseTab = vi.fn();
    const { rerender } = render(
        <CustomAppWorkspace {...baseProps} layout="full" onOpenChat={onOpenChat} onCloseTab={onCloseTab} />,
    );
    fireEvent.click(screen.getByTestId('custom-app-chat'));
    expect(onOpenChat).toHaveBeenCalledOnce();

    rerender(
        <CustomAppWorkspace {...baseProps} layout="split" onOpenChat={onOpenChat} onCloseTab={onCloseTab} />,
    );
    fireEvent.click(screen.getByTestId('close-tab-app:text-lab'));
    expect(onCloseTab).toHaveBeenCalledWith('app:text-lab');
});

test('reloads the app iframe from its split-view tab', () => {
    render(<CustomAppWorkspace {...baseProps} layout="split" />);
    const frame = screen.getByTestId('custom-app-frame');

    fireEvent.click(screen.getByTestId('custom-app-tab-reload'));

    expect(screen.getByTestId('custom-app-frame')).not.toBe(frame);
});
