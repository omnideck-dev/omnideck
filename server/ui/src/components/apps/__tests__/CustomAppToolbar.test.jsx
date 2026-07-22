import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import CustomAppToolbar, {
    CustomAppDockActions,
    CustomAppError,
    CustomAppReloadAction,
} from '../CustomAppToolbar.jsx';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };

test('exposes app-level shell actions without owning workspace tabs', () => {
    const handlers = {
        onOpenApps: vi.fn(),
        onOpenChat: vi.fn(),
        onClose: vi.fn(),
        onToggleHome: vi.fn(),
        onReload: vi.fn(),
    };
    render(<CustomAppToolbar app={APP} isHome={false} {...handlers} />);

    fireEvent.click(screen.getByTestId('custom-app-back'));
    fireEvent.click(screen.getByTestId('custom-app-chat'));
    fireEvent.click(screen.getByTestId('custom-app-close'));
    fireEvent.click(screen.getByTestId('custom-app-home-toggle'));
    fireEvent.click(screen.getByTestId('custom-app-reload'));

    expect(handlers.onOpenApps).toHaveBeenCalledOnce();
    expect(handlers.onOpenChat).toHaveBeenCalledOnce();
    expect(handlers.onClose).toHaveBeenCalledOnce();
    expect(handlers.onToggleHome).toHaveBeenCalledOnce();
    expect(handlers.onReload).toHaveBeenCalledOnce();
});

test('keeps Home and reload actions stable when Home assignment changes', () => {
    const handlers = {
        onOpenApps: vi.fn(),
        onOpenChat: vi.fn(),
        onClose: vi.fn(),
        onToggleHome: vi.fn(),
        onReload: vi.fn(),
    };
    const { rerender } = render(<CustomAppToolbar app={APP} isHome={false} {...handlers} />);
    rerender(<CustomAppToolbar app={APP} isHome {...handlers} />);

    expect(screen.getByTestId('custom-app-home-toggle')).toHaveTextContent('Remove from Home');
    expect(screen.getByTestId('custom-app-reload')).toBeInTheDocument();
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

test('offers expand and reload actions from the dock', () => {
    const onExpand = vi.fn();
    const onReload = vi.fn();
    render(<CustomAppDockActions onExpand={onExpand} onReload={onReload} />);

    fireEvent.click(screen.getByTestId('custom-app-expand'));
    fireEvent.click(screen.getByTestId('custom-app-tab-reload'));

    expect(onExpand).toHaveBeenCalledOnce();
    expect(onReload).toHaveBeenCalledOnce();
});
