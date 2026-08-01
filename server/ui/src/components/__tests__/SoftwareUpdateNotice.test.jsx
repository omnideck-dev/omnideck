import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

// The notice reads one preference and writes one preference.
function settings({ notify = true } = {}) {
    const calls = [];
    global.fetch = vi.fn(async (url, options) => {
        calls.push({ url, options });
        return { ok: true, json: async () => ({ software_updates_notify: notify }) };
    });
    return calls;
}

// Lets the mounting effects settle: the notice asks for the current update and
// for the preference as it stands.
const settle = () => act(async () => { await Promise.resolve(); await Promise.resolve(); });

afterEach(() => {
    delete window.omnideckDesktop;
    delete global.fetch;
    vi.restoreAllMocks();
});

describe('SoftwareUpdateNotice', () => {
    it('shows nothing in a browser, where nothing could be installed', async () => {
        settings();

        render(<SoftwareUpdateNotice />);
        await settle();

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('shows nothing until there is an update to show', async () => {
        bridge();
        settings();

        render(<SoftwareUpdateNotice />);
        await settle();

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('names the version and offers every answer', async () => {
        const desktop = bridge();
        settings();
        render(<SoftwareUpdateNotice />);
        await settle();

        act(() => desktop.announce({ version: '0.2.0' }));

        expect(screen.getByText('Omnideck 0.2.0 is ready')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Skip this version' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Don’t show this again/ })).toBeInTheDocument();
        // Turning the notice off has to leave somewhere to go.
        expect(screen.getByText('Updates stay available in Settings.')).toBeInTheDocument();
    });

    it('stays silent for someone who asked not to be told', async () => {
        const desktop = bridge();
        settings({ notify: false });
        render(<SoftwareUpdateNotice />);
        await settle();

        act(() => desktop.announce({ version: '0.2.0' }));

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('installs only when asked to', async () => {
        const desktop = bridge();
        settings();
        render(<SoftwareUpdateNotice />);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Update now' }));

        expect(desktop.installUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
    });

    it('skipping asks the shell to remember, and does not install', async () => {
        const desktop = bridge();
        settings();
        render(<SoftwareUpdateNotice />);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Skip this version' }));

        expect(desktop.skipUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.installUpdate).not.toHaveBeenCalled();
    });

    it('never showing again is a preference, not an answer about this version', async () => {
        const desktop = bridge();
        const calls = settings();
        render(<SoftwareUpdateNotice />);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: /Don’t show this again/ }));

        await waitFor(() => {
            expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
        });
        const written = calls.find((call) => call.options?.method === 'PUT');
        expect(JSON.parse(written.options.body)).toEqual({ software_updates_notify: false });
        // The update itself is untouched, so Settings goes on offering it.
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
        expect(desktop.installUpdate).not.toHaveBeenCalled();
    });

    it('an update found before this page existed is asked for, not waited on', async () => {
        const desktop = bridge();
        desktop.currentUpdate = vi.fn().mockResolvedValue({ version: '0.3.0' });
        settings();

        render(<SoftwareUpdateNotice />);
        await settle();

        expect(screen.getByText('Omnideck 0.3.0 is ready')).toBeInTheDocument();
    });

    it('a withdrawn update takes its notice with it', async () => {
        const desktop = bridge();
        settings();
        render(<SoftwareUpdateNotice />);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        act(() => desktop.announce(null));

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('stops listening once it is gone', async () => {
        const desktop = bridge();
        settings();
        const { unmount } = render(<SoftwareUpdateNotice />);
        await settle();

        unmount();

        expect(desktop.unsubscribed).toBe(true);
    });
});
