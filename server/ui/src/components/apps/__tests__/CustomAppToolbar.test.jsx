import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import CustomAppToolbar, { CustomAppError, CustomAppReloadAction } from '../CustomAppToolbar.jsx';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };

test('exposes app-level shell actions without owning workspace tabs', () => {
    const handlers = {
        onOpenApps: vi.fn(),
        onOpenChat: vi.fn(),
        onToggleHome: vi.fn(),
        onReload: vi.fn(),
    };
    render(<CustomAppToolbar app={APP} origin="apps" isHome={false} {...handlers} />);

    fireEvent.click(screen.getByTestId('custom-app-back'));
    fireEvent.click(screen.getByTestId('custom-app-chat'));
    fireEvent.click(screen.getByTestId('custom-app-home-toggle'));
    fireEvent.click(screen.getByTestId('custom-app-reload'));

    expect(handlers.onOpenApps).toHaveBeenCalledOnce();
    expect(handlers.onOpenChat).toHaveBeenCalledOnce();
    expect(handlers.onToggleHome).toHaveBeenCalledOnce();
    expect(handlers.onReload).toHaveBeenCalledOnce();
});

test('renders optional split-tab reload and errors', () => {
    const onReload = vi.fn();
    render(
        <>
            <CustomAppReloadAction onReload={onReload} />
            <CustomAppError message="Could not update Home app" />
        </>,
    );

    fireEvent.click(screen.getByTestId('custom-app-tab-reload'));
    expect(onReload).toHaveBeenCalledOnce();
    expect(screen.getByText('Could not update Home app')).toBeInTheDocument();
});
