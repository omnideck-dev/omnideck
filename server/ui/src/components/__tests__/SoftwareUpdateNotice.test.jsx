import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SoftwareUpdateNotice from '../SoftwareUpdateNotice.jsx';

// Stands in for the desktop application's side of the bridge, holding on to the
// listener so a test can announce an update the way the shell does.
function bridge() {
    const desktop = {
        announce: null,
        unsubscribed: false,
        currentUpdate: vi.fn().mockResolvedValue(null),
        installUpdate: vi.fn().mockResolvedValue(undefined),
        skipUpdate: vi.fn().mockResolvedValue(undefined),
        onUpdate: (listener) => {
            desktop.announce = listener;
            return () => { desktop.unsubscribed = true; };
        },
    };
    window.omnideckDesktop = desktop;
    return desktop;
}

afterEach(() => {
    delete window.omnideckDesktop;
});

describe('SoftwareUpdateNotice', () => {
    it('shows nothing in a browser, where nothing could be installed', () => {
        render(<SoftwareUpdateNotice />);

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('shows nothing until there is an update to show', () => {
        bridge();

        render(<SoftwareUpdateNotice />);

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('names the version and offers both answers', () => {
        const desktop = bridge();
        render(<SoftwareUpdateNotice />);

        act(() => desktop.announce({ version: '0.2.0' }));

        expect(screen.getByText('Omnideck 0.2.0 is ready')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Skip this version' })).toBeInTheDocument();
    });

    it('installs only when asked to', () => {
        const desktop = bridge();
        render(<SoftwareUpdateNotice />);
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Update now' }));

        expect(desktop.installUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
    });

    it('skipping asks the shell to remember, and does not install', () => {
        const desktop = bridge();
        render(<SoftwareUpdateNotice />);
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Skip this version' }));

        expect(desktop.skipUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.installUpdate).not.toHaveBeenCalled();
    });

    it('an update found before this page existed is asked for, not waited on', async () => {
        const desktop = bridge();
        desktop.currentUpdate = vi.fn().mockResolvedValue({ version: '0.3.0' });

        render(<SoftwareUpdateNotice />);
        await act(async () => { await Promise.resolve(); });

        expect(screen.getByText('Omnideck 0.3.0 is ready')).toBeInTheDocument();
    });

    it('a withdrawn update takes its notice with it', () => {
        const desktop = bridge();
        render(<SoftwareUpdateNotice />);
        act(() => desktop.announce({ version: '0.2.0' }));

        act(() => desktop.announce(null));

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('stops listening once it is gone', () => {
        const desktop = bridge();
        const { unmount } = render(<SoftwareUpdateNotice />);

        unmount();

        expect(desktop.unsubscribed).toBe(true);
    });
});
