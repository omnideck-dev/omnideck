import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import IntegrationSetupFlow from '../setup/IntegrationSetupFlow.jsx';

const CATALOG = [{
    id: 'http',
    title: 'Custom HTTP API',
    description: 'Any REST endpoint with a static token',
    category: 'Custom',
    operations: [{
        id: 'http.request',
        title: 'Call API',
        description: 'Make an authenticated HTTP request.',
    }],
}];
const CONNECTION = {
    id: 'http_sales-api',
    slug: 'http',
    label: 'Sales API',
    state: 'running',
    operation_grants: [],
    operations: CATALOG[0].operations,
};

function response(body, status = 200) {
    return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(body),
    });
}

async function connectHttp() {
    fireEvent.click(screen.getByTestId('provider-http'));
    fireEvent.click(screen.getByTestId('wizard-next'));
    fireEvent.change(screen.getByTestId('wizard-label'), { target: { value: 'Sales API' } });
    fireEvent.change(screen.getByTestId('wizard-base-url'), { target: { value: 'https://api.example.com' } });
    fireEvent.change(screen.getByTestId('wizard-token'), { target: { value: 'secret' } });
    fireEvent.click(screen.getByTestId('wizard-submit'));
    await screen.findByText('Choose tools');
}

afterEach(() => vi.restoreAllMocks());

describe('IntegrationSetupFlow', () => {
    it('creates with zero grants, then saves only the explicitly selected tools', async () => {
        const onComplete = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url === '/api/integrations' && options?.method === 'POST') {
                return response(CONNECTION, 201);
            }
            if (url === '/api/integrations/http_sales-api' && options?.method === 'PATCH') {
                return response({ ...CONNECTION, operation_grants: ['http.request'] });
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<IntegrationSetupFlow catalog={CATALOG} onExit={vi.fn()} onComplete={onComplete} />);

        await connectHttp();
        const createCall = globalThis.fetch.mock.calls[0];
        expect(JSON.parse(createCall[1].body).operation_grants).toEqual([]);

        fireEvent.click(screen.getByTestId('integration-tool-http.request'));
        fireEvent.click(screen.getByTestId('wizard-next'));
        expect(screen.getByText('Review integration')).toBeInTheDocument();
        fireEvent.click(screen.getByTestId('wizard-done'));

        await waitFor(() => expect(onComplete).toHaveBeenCalled());
        const patchCall = globalThis.fetch.mock.calls[1];
        expect(JSON.parse(patchCall[1].body)).toEqual({ operation_grants: ['http.request'] });
    });

    it('deletes the setup-owned connection when setup is cancelled after authentication', async () => {
        const onExit = vi.fn();
        const onComplete = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url === '/api/integrations' && options?.method === 'POST') {
                return response(CONNECTION, 201);
            }
            if (url === '/api/integrations/http_sales-api' && options?.method === 'DELETE') {
                return response({});
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<IntegrationSetupFlow catalog={CATALOG} onExit={onExit} onComplete={onComplete} />);

        await connectHttp();
        fireEvent.click(screen.getByTestId('wizard-exit'));

        await waitFor(() => expect(onExit).toHaveBeenCalled());
        expect(onComplete).not.toHaveBeenCalled();
        expect(globalThis.fetch).toHaveBeenCalledTimes(2);
        expect(globalThis.fetch.mock.calls[1]).toEqual([
            '/api/integrations/http_sales-api',
            { method: 'DELETE' },
        ]);
    });

    it('stays open and reports a cleanup failure instead of hiding the connection', async () => {
        const onExit = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url === '/api/integrations' && options?.method === 'POST') {
                return response(CONNECTION, 201);
            }
            if (url === '/api/integrations/http_sales-api' && options?.method === 'DELETE') {
                return response({
                    error: { code: 'UNAVAILABLE', message: 'Supervisor unavailable' },
                }, 503);
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<IntegrationSetupFlow catalog={CATALOG} onExit={onExit} onComplete={vi.fn()} />);

        await connectHttp();
        fireEvent.click(screen.getByTestId('wizard-exit'));

        expect(await screen.findByText("Couldn't cancel setup")).toBeInTheDocument();
        expect(screen.getByText('Supervisor unavailable')).toBeInTheDocument();
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(onExit).not.toHaveBeenCalled();
    });

    it('keeps a zero-tool connection only when Review is finished', async () => {
        const onComplete = vi.fn();
        globalThis.fetch = vi.fn((url, options) => {
            if (url === '/api/integrations' && options?.method === 'POST') {
                return response(CONNECTION, 201);
            }
            if (url === '/api/integrations/http_sales-api' && options?.method === 'PATCH') {
                return response(CONNECTION);
            }
            throw new Error(`Unexpected request: ${url}`);
        });
        render(<IntegrationSetupFlow catalog={CATALOG} onExit={vi.fn()} onComplete={onComplete} />);

        await connectHttp();
        fireEvent.click(screen.getByTestId('wizard-next'));
        fireEvent.click(screen.getByTestId('wizard-done'));

        await waitFor(() => expect(onComplete).toHaveBeenCalledWith(CONNECTION));
        expect(JSON.parse(globalThis.fetch.mock.calls[1][1].body)).toEqual({
            operation_grants: [],
        });
    });
});
