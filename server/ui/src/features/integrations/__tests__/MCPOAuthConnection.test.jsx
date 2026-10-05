import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import MCPOAuthConnection from '../setup/connection-adapters/MCPOAuthConnection.jsx';
import SlackOAuthConnection from '../setup/connection-adapters/SlackOAuthConnection.jsx';
import { cancelIntegrationOAuth } from '../api/integrationsApi.js';

const response = body => Promise.resolve({ ok: true, json: async () => body });

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('MCP connection setup', () => {
    it('connects Slack with an internal app, not a token or client secret', async () => {
        vi.useFakeTimers();
        const connected = vi.fn();
        const pending = vi.fn();
        vi.spyOn(window, 'open').mockReturnValue(null);
        globalThis.fetch = vi.fn((url, options) => {
            if (url.includes('/connection-settings')) return response({ redirect_uri: 'http://localhost:9000/callback', slack_manifest: { oauth_config: { pkce_enabled: true } } });
            if (options?.method === 'POST') {
                expect(url).toBe('/api/integrations/mcp/oauth/start');
                expect(JSON.parse(options.body)).toEqual({ slug: 'slack', label: 'Slack', client_id: '123.456' });
                return response({ state: 'mcp_attempt', status: 'pending', authorize_url: 'https://slack.com/authorize' });
            }
            expect(url).toBe('/api/integrations/mcp/oauth/status/mcp_attempt');
            return response({ status: 'success', integration_id: 'slack_fixture' });
        });
        render(<SlackOAuthConnection entry={{ id: 'slack', title: 'Slack' }} onBack={vi.fn()}
            onConnectedId={connected} onPendingOAuthChange={pending} />);
        expect(screen.queryByLabelText('Server URL')).not.toBeInTheDocument();
        expect(screen.queryByLabelText(/Client secret/i)).not.toBeInTheDocument();
        expect(screen.getByText(/private channels and direct messages/)).toBeInTheDocument();
        expect(screen.queryByText(/connect public-channel tools/)).not.toBeInTheDocument();
        await act(async () => {});
        expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
        expect(screen.getByLabelText(/Redirect URL/)).toHaveValue('http://localhost:9000/callback');
        expect(screen.getByTestId('slack-app-setup')).not.toHaveAttribute('open');
        fireEvent.change(screen.getByLabelText(/Slack Client ID/), { target: { value: '123.456' } });
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Connect' })); });
        expect(pending).toHaveBeenCalledWith('mcp_attempt');
        expect(screen.getByRole('button', { name: 'Reopen sign-in' })).toBeEnabled();
        expect(screen.getByRole('link', { name: 'Open sign-in in a new tab' })).toHaveAttribute('href', 'https://slack.com/authorize');
        await act(async () => { await vi.advanceTimersByTimeAsync(700); });
        expect(connected).toHaveBeenCalledWith('slack_fixture');
    });

    it('blocks sign-in when saved settings cannot be loaded', async () => {
        globalThis.fetch = vi.fn(() => Promise.reject(new Error('Unavailable')));
        render(<SlackOAuthConnection entry={{ id: 'slack', title: 'Slack' }} onBack={vi.fn()} />);
        await act(async () => {});
        expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
        expect(screen.getByText('Connection settings unavailable')).toBeInTheDocument();
    });

    it('supports a server needing no sign-in and preserves reconnect identity', async () => {
        const connected = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url.includes('/connection-settings')) return response({ redirect_uri: 'http://localhost:9000/callback' });
            expect(JSON.parse(options.body)).toMatchObject({ reconnect_id: 'mcp_existing', client_id: '' });
            return response({ state: 'mcp_attempt', status: 'success', integration_id: 'mcp_existing' });
        });
        render(<MCPOAuthConnection entry={{ id: 'mcp', title: 'MCP server' }}
            existingConnection={{ id: 'mcp_existing', label: 'Work service' }} onBack={vi.fn()} onConnectedId={connected} />);
        fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://example.test/mcp' } });
        await act(async () => {});
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Connect' })); });
        expect(connected).toHaveBeenCalledWith('mcp_existing');
    });

    it('routes cancellation through the same owned MCP attempt', async () => {
        globalThis.fetch = vi.fn(() => response({ status: 'cancelled' }));
        await cancelIntegrationOAuth('mcp_attempt');
        expect(fetch).toHaveBeenCalledWith('/api/integrations/mcp/oauth/status/mcp_attempt', { method: 'DELETE' });
    });

    it('reconnects Slack without changing its identity or selecting newly discovered tools', async () => {
        const connected = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url.includes('/connection-settings')) {
                expect(url).toContain('connection_id=slack_existing');
                return response({ redirect_uri: 'http://localhost:9000/callback', connection: { client_id: '123.456' } });
            }
            expect(JSON.parse(options.body)).toEqual({ slug: 'slack', label: 'Work Slack', reconnect_id: 'slack_existing', client_id: '123.456' });
            return response({ state: 'mcp_attempt', status: 'success', integration_id: 'slack_existing' });
        });
        render(<SlackOAuthConnection entry={{ id: 'slack', title: 'Slack' }}
            existingConnection={{ id: 'slack_existing', label: 'Work Slack' }} onBack={vi.fn()} onConnectedId={connected} />);
        expect(screen.getByText(/Your selected tools stay the same/)).toBeInTheDocument();
        expect(screen.getByLabelText('Connection name')).toBeDisabled();
        await act(async () => {});
        expect(screen.getByLabelText(/Slack Client ID/)).toHaveValue('123.456');
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Connect' })); });
        expect(connected).toHaveBeenCalledWith('slack_existing');
    });

    it('rejects tokens and malformed client IDs before sign-in', async () => {
        globalThis.fetch = vi.fn(() => response({ redirect_uri: 'http://localhost:9000/callback' }));
        render(<SlackOAuthConnection entry={{ id: 'slack', title: 'Slack' }} onBack={vi.fn()} />);
        await act(async () => {});
        for (const value of ['xoxb-secret', 'not-an-id', '123']) {
            fireEvent.change(screen.getByLabelText(/Slack Client ID/), { target: { value } });
            expect(screen.getByRole('button', { name: 'Connect' })).toBeDisabled();
        }
    });
});
