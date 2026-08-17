import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SoftwareUpdateNotice from '../SoftwareUpdateNotice.jsx';
import { OmnideckHostProvider } from '../../features/app/OmnideckHost.jsx';

// Stands in for the desktop application's side of the bridge, holding on to the
// listener so a test can announce an update the way the shell does.
function bridge() {
    const desktop = {
        announce: null,
        unsubscribed: false,
        currentUpdate: vi.fn().mockResolvedValue(null),
        installUpdate: vi.fn().mockResolvedValue(undefined),
        deferUpdate: vi.fn().mockResolvedValue(undefined),
        skipUpdate: vi.fn().mockResolvedValue(undefined),
        onUpdate: (listener) => {
            desktop.announce = listener;
            return () => { desktop.unsubscribed = true; };
        },
    };
    return desktop;
}

// Renders as the desktop application would, or as a browser would when the
// host is null.
function renderNotice(host) {
    return render(
        <OmnideckHostProvider host={host}>
            <SoftwareUpdateNotice />
        </OmnideckHostProvider>,
    );
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
    delete global.fetch;
    vi.restoreAllMocks();
});

describe('SoftwareUpdateNotice', () => {
    it('shows nothing in a browser, where nothing could be installed', async () => {
        settings();

        renderNotice(null);
        await settle();

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('shows nothing until there is an update to show', async () => {
        const desktop = bridge();
        settings();

        renderNotice(desktop);
        await settle();

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('names the version and offers every answer', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();

        act(() => desktop.announce({ version: '0.2.0' }));

        expect(screen.getByText('Omnideck 0.2.0 is ready')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /What’s new/ })).toHaveAttribute(
            'href',
            'https://github.com/omnideck-dev/omnideck/releases/tag/app-v0.2.0',
        );
        expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Later' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Skip this version' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Don’t show these again/ })).toBeInTheDocument();
        // Turning the notice off has to leave somewhere to go.
        expect(screen.getByText('Updates stay available in Settings.')).toBeInTheDocument();
    });

    it('stays silent for someone who asked not to be told', async () => {
        const desktop = bridge();
        settings({ notify: false });
        renderNotice(desktop);
        await settle();

        act(() => desktop.announce({ version: '0.2.0' }));

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('installs only when asked to', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Update now' }));

        expect(desktop.installUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
    });

    it('skipping asks the shell to remember, and does not install', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Skip this version' }));

        expect(desktop.skipUpdate).toHaveBeenCalledTimes(1);
        expect(desktop.installUpdate).not.toHaveBeenCalled();
    });

    it('never showing again is a preference, not an answer about this version', async () => {
        const desktop = bridge();
        const calls = settings();
        renderNotice(desktop);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: /Don’t show these again/ }));

        await waitFor(() => {
            expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
        });
        const written = calls.find((call) => call.options?.method === 'PUT');
        expect(JSON.parse(written.options.body)).toEqual({ software_updates_notify: false });
        // The update itself is untouched, so Settings goes on offering it.
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
        expect(desktop.installUpdate).not.toHaveBeenCalled();
    });

    it('later asks for it at the next open without turning anything on', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        fireEvent.click(screen.getByRole('button', { name: 'Later' }));

        expect(desktop.deferUpdate).toHaveBeenCalledTimes(1);
        // It is neither installed now nor refused: it waits.
        expect(desktop.installUpdate).not.toHaveBeenCalled();
        expect(desktop.skipUpdate).not.toHaveBeenCalled();
    });

    it('an update already put off is not asked about again', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();

        act(() => desktop.announce({ version: '0.2.0', deferred: true }));

        // Settled, so the notice says nothing. Settings still shows it.
        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('an update found before this page existed is asked for, not waited on', async () => {
        const desktop = bridge();
        desktop.currentUpdate = vi.fn().mockResolvedValue({ version: '0.3.0' });
        settings();

        renderNotice(desktop);
        await settle();

        expect(screen.getByText('Omnideck 0.3.0 is ready')).toBeInTheDocument();
    });

    it('a withdrawn update takes its notice with it', async () => {
        const desktop = bridge();
        settings();
        renderNotice(desktop);
        await settle();
        act(() => desktop.announce({ version: '0.2.0' }));

        act(() => desktop.announce(null));

        expect(screen.queryByTestId('software-update-notice')).not.toBeInTheDocument();
    });

    it('stops listening once it is gone', async () => {
        const desktop = bridge();
        settings();
        const { unmount } = renderNotice(desktop);
        await settle();

        unmount();

        expect(desktop.unsubscribed).toBe(true);
    });
});
