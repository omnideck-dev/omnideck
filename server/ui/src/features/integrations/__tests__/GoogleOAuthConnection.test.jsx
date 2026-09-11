import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import GoogleOAuthConnection from '../setup/connection-adapters/GoogleOAuthConnection.jsx';

const ENTRY = {
    id: 'google_workspace',
    title: 'Google Workspace',
};

function response(body) {
    return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve(body),
    });
}

afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe('GoogleOAuthConnection', () => {
    it('keeps the complete Google Cloud setup walkthrough in the connection flow', () => {
        render(
            <GoogleOAuthConnection
                entry={ENTRY}
                onBack={vi.fn()}
                onConnectedId={vi.fn()}
            />,
        );

        const setup = screen.getByTestId('google-cloud-setup');
        expect(setup).not.toHaveAttribute('open');
        fireEvent.click(screen.getByText('Google Cloud setup'));
        expect(setup).toHaveAttribute('open');
        expect(screen.getByText('1', { selector: 'summary span' })).toBeInTheDocument();
        expect(screen.getByText('2', { selector: 'summary span' })).toBeInTheDocument();
        expect(screen.getByText('3', { selector: 'summary span' })).toBeInTheDocument();
        expect(screen.getByText('4', { selector: 'summary span' })).toBeInTheDocument();
        expect(screen.getByText('5', { selector: 'summary span' })).toBeInTheDocument();
        expect(screen.getByText('Enable the Google APIs')).toBeInTheDocument();
        expect(screen.getByText('Choose the publishing status')).toBeInTheDocument();
        expect(screen.getByText('Create a desktop OAuth client')).toBeInTheDocument();
    });

    it('keeps polling through the committing state until the connection succeeds', async () => {
        vi.useFakeTimers();
        const onBusyChange = vi.fn();
        const onConnectedId = vi.fn();
        const statuses = [
            { status: 'committing' },
            { status: 'success', integration_id: 'google_workspace_personal' },
        ];
        globalThis.fetch = vi.fn((url, options) => {
            if (url === '/api/integrations/oauth/start' && options?.method === 'POST') {
                return response({
                    state: 'oauth-state',
                    authorize_url: 'https://accounts.google.test/authorize',
                });
            }
            if (url === '/api/integrations/oauth/status/oauth-state') {
                return response(statuses.shift());
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        vi.spyOn(window, 'open').mockReturnValue(null);

        render(
            <GoogleOAuthConnection
                entry={ENTRY}
                onBack={vi.fn()}
                onConnectedId={onConnectedId}
                onBusyChange={onBusyChange}
                onPendingOAuthChange={vi.fn()}
            />,
        );
        fireEvent.change(screen.getByTestId('wizard-email'), {
            target: { value: 'person@example.com' },
        });
        fireEvent.change(screen.getByTestId('oauth-client-id'), {
            target: { value: 'client-id' },
        });
        fireEvent.change(screen.getByTestId('oauth-client-secret'), {
            target: { value: 'client-secret' },
        });

        await act(async () => {
            fireEvent.click(screen.getByTestId('oauth-authorize'));
        });
        expect(screen.getByText('Waiting for authorization…')).toBeInTheDocument();

        await act(async () => {
            await vi.advanceTimersByTimeAsync(700);
        });
        expect(screen.getByText('Finishing connection…')).toBeInTheDocument();
        expect(screen.getByTestId('oauth-reopen-popup')).toBeDisabled();

        await act(async () => {
            await vi.advanceTimersByTimeAsync(1000);
        });
        expect(onConnectedId).toHaveBeenCalledWith('google_workspace_personal');
        expect(onBusyChange).toHaveBeenCalledWith(true);
        expect(onBusyChange).toHaveBeenLastCalledWith(false);
        expect(statuses).toHaveLength(0);
    });

    it('reconnects without asking for or replacing the connection suffix', async () => {
        globalThis.fetch = vi.fn(() => response({
            state: 'oauth-state',
            authorize_url: 'https://accounts.google.test/authorize',
        }));
        vi.spyOn(window, 'open').mockReturnValue(null);

        render(
            <GoogleOAuthConnection
                entry={ENTRY}
                existingConnection={{
                    id: 'google_workspace_personal',
                    label: 'Google Workspace · personal',
                }}
                onBack={vi.fn()}
                onConnectedId={vi.fn()}
            />,
        );

        expect(screen.queryByTestId('wizard-email')).not.toBeInTheDocument();
        fireEvent.change(screen.getByTestId('oauth-client-id'), {
            target: { value: 'client-id' },
        });
        fireEvent.change(screen.getByTestId('oauth-client-secret'), {
            target: { value: 'client-secret' },
        });
        await act(async () => {
            fireEvent.click(screen.getByTestId('oauth-authorize'));
        });

        const payload = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
        expect(payload.reconnect_id).toBe('google_workspace_personal');
        expect(payload).not.toHaveProperty('user_suffix');
    });
});
