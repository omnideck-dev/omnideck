import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import IntegrationSetupFlow from '../setup/IntegrationSetupFlow.jsx';
import IntegrationReconnectFlow from '../setup/IntegrationReconnectFlow.jsx';

const response = body => Promise.resolve({ ok: true, json: async () => body });
const PROVIDERS = ['mcp', 'slack', 'google_workspace'];

afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

async function startFlow({ slug, reconnect, immediate, missing = false }) {
    vi.useFakeTimers();
    vi.spyOn(window, 'open').mockReturnValue(null);
    const entry = { id: slug, title: slug, category: 'Services' };
    const connection = {
        id: `${slug}_saved`, slug, label: 'Work account', state: 'running',
        operation_grants: [], operations: [],
    };
    const onComplete = vi.fn();
    const onExit = vi.fn();
    const load = vi.fn();
    if (missing) load.mockResolvedValueOnce({ connections: [] });
    else load.mockRejectedValueOnce(new Error('Connection list unavailable'));
    load.mockResolvedValue({ connections: [connection] });
    const state = slug === 'google_workspace' ? 'google_attempt' : 'mcp_attempt';
    const success = { state, status: 'success', integration_id: connection.id };
    globalThis.fetch = vi.fn((url, options) => {
        if (url.includes('/connection-settings')) return response({
            redirect_uri: 'http://localhost:9000/callback',
            connection: { endpoint: 'https://example.test/mcp', client_id: '123.456', issuer: 'https://example.test' },
        });
        if (url.endsWith('/start')) return response(immediate ? success : {
            state, status: 'pending', authorize_url: 'https://example.test/authorize',
        });
        if (url.includes('/status/')) return response(success);
        if (url === '/api/integrations') return load().then(response);
        if (url === `/api/integrations/${connection.id}` && options?.method === 'DELETE') return response({});
        throw new Error(`Unexpected request: ${url}`);
    });
    render(reconnect
        ? <IntegrationReconnectFlow connection={connection} catalogEntry={entry} onExit={onExit} onComplete={onComplete} />
        : <IntegrationSetupFlow catalog={[entry]} onExit={onExit} onComplete={onComplete} />);
    if (!reconnect) {
        fireEvent.click(screen.getByTestId(`provider-${slug}`));
        fireEvent.click(screen.getByTestId('wizard-next'));
    }
    await act(async () => {});
    if (slug === 'google_workspace') {
        if (!reconnect) fireEvent.change(screen.getByTestId('wizard-email'), { target: { value: 'demo@example.test' } });
        fireEvent.change(screen.getByTestId('oauth-client-id'), { target: { value: 'client' } });
        fireEvent.change(screen.getByTestId('oauth-client-secret'), { target: { value: 'secret' } });
    } else if (slug === 'mcp') {
        fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://example.test/mcp' } });
    } else {
        fireEvent.change(screen.getByLabelText(/Slack Client ID/), { target: { value: '123.456' } });
    }
    await act(async () => {
        fireEvent.click(slug === 'google_workspace'
            ? screen.getByTestId('oauth-authorize')
            : screen.getByRole('button', { name: 'Connect' }));
    });
    if (!immediate) await act(async () => { await vi.advanceTimersByTimeAsync(700); });
    expect(screen.getByRole('heading', { name: 'Sign-in complete' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry loading connection' })).toBeEnabled();
    expect(load).toHaveBeenCalledTimes(1);
    return { connection, onComplete, onExit, load };
}

describe('OAuth saved-connection recovery', () => {
    for (const reconnect of [false, true]) {
        for (const immediate of [false, true]) {
            it.each(PROVIDERS)(`retries only the saved connection for %s (reconnect=${reconnect}, immediate=${immediate})`, async slug => {
                const { connection, onComplete, load } = await startFlow({ slug, reconnect, immediate });
                await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
                expect(load).toHaveBeenCalledTimes(1);
                await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry loading connection' })); });
                expect(load).toHaveBeenCalledTimes(2);
                expect(globalThis.fetch.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(1);
                expect(window.open).toHaveBeenCalledTimes(immediate ? 0 : 1);
                if (reconnect) expect(onComplete).toHaveBeenCalledWith(connection);
                else {
                    expect(screen.getByText('Choose tools')).toBeInTheDocument();
                    expect(onComplete).not.toHaveBeenCalled();
                }
            });
        }
    }

    it('retains the saved ID across missing records and repeated reload failures', async () => {
        const { load } = await startFlow({ slug: 'mcp', reconnect: false, immediate: true, missing: true });
        load.mockRejectedValueOnce(new Error('Still unavailable'));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry loading connection' })); });
        expect(screen.getByText('Still unavailable')).toBeInTheDocument();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Retry loading connection' })); });
        expect(screen.getByText('Choose tools')).toBeInTheDocument();
        expect(screen.queryByText('Still unavailable')).not.toBeInTheDocument();
        expect(globalThis.fetch.mock.calls.filter(([url]) => url.endsWith('/start'))).toHaveLength(1);
    });

    it('blocks duplicate reloads and dismissal while the saved connection is loading', async () => {
        const { connection, load } = await startFlow({ slug: 'mcp', reconnect: false, immediate: true });
        let finish;
        load.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
        fireEvent.click(screen.getByRole('button', { name: 'Retry loading connection' }));
        expect(screen.getByRole('button', { name: 'Loading…' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Exit setup' })).toBeDisabled();
        expect(screen.getByRole('button', { name: 'Close' })).toBeDisabled();
        await act(async () => { finish({ connections: [connection] }); });
        expect(screen.getByText('Choose tools')).toBeInTheDocument();
    });

    it.each([false, true])('exits reload recovery with correct connection ownership (reconnect=%s)', async reconnect => {
        const { connection, onExit } = await startFlow({ slug: 'mcp', reconnect, immediate: true });
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Exit setup' })); });
        expect(onExit).toHaveBeenCalledTimes(1);
        const deletes = globalThis.fetch.mock.calls.filter(([, options]) => options?.method === 'DELETE');
        expect(deletes).toEqual(reconnect ? [] : [[`/api/integrations/${connection.id}`, { method: 'DELETE' }]]);
    });

    it('keeps the saved ID when cancelling the new connection fails', async () => {
        const { connection, onExit } = await startFlow({ slug: 'mcp', reconnect: false, immediate: true });
        globalThis.fetch.mockRejectedValueOnce(new Error('Cleanup unavailable'));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Exit setup' })); });
        expect(screen.getByText('Cleanup unavailable')).toBeInTheDocument();
        expect(onExit).not.toHaveBeenCalled();
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Exit setup' })); });
        expect(onExit).toHaveBeenCalledTimes(1);
        expect(globalThis.fetch.mock.calls.filter(([, options]) => options?.method === 'DELETE')).toEqual([
            [`/api/integrations/${connection.id}`, { method: 'DELETE' }],
            [`/api/integrations/${connection.id}`, { method: 'DELETE' }],
        ]);
    });
});
