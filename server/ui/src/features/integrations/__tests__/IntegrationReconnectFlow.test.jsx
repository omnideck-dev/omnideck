import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import IntegrationReconnectFlow from '../setup/IntegrationReconnectFlow.jsx';

const ENTRY = {
    id: 'http',
    title: 'Custom HTTP API',
    description: 'Any REST endpoint with a static token',
};
const CONNECTION = {
    id: 'http_sales-api',
    slug: 'http',
    label: 'Sales API',
    state: 'running',
    operation_grants: ['http.request'],
    operations: [{ id: 'http.request', title: 'Call API', description: 'Call it.' }],
};

afterEach(() => vi.restoreAllMocks());

describe('IntegrationReconnectFlow', () => {
    it('replaces credentials on the existing connection instead of adding a duplicate', async () => {
        const onComplete = vi.fn();
        globalThis.fetch = vi.fn(() => Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(CONNECTION),
        }));
        render(
            <IntegrationReconnectFlow
                connection={CONNECTION}
                catalogEntry={ENTRY}
                onExit={vi.fn()}
                onComplete={onComplete}
            />,
        );

        expect(screen.getByTestId('wizard-label')).toBeDisabled();
        fireEvent.change(screen.getByTestId('wizard-base-url'), {
            target: { value: 'https://api.example.com' },
        });
        fireEvent.change(screen.getByTestId('wizard-token'), {
            target: { value: 'replacement-secret' },
        });
        fireEvent.click(screen.getByTestId('wizard-submit'));

        await waitFor(() => expect(onComplete).toHaveBeenCalledWith(CONNECTION));
        expect(globalThis.fetch).toHaveBeenCalledWith(
            '/api/integrations/http_sales-api/reconnect',
            expect.objectContaining({ method: 'POST' }),
        );
        const payload = JSON.parse(globalThis.fetch.mock.calls[0][1].body);
        expect(payload).toEqual({
            auth_blob: {
                base_url: 'https://api.example.com',
                header_name: 'Authorization',
                header_template: 'Bearer {token}',
                token: 'replacement-secret',
            },
        });
    });
});
