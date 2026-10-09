import { afterEach, describe, expect, it, vi } from 'vitest';
import { listIntegrationCatalog, listIntegrationConnections } from '../api/integrationsApi.js';

afterEach(() => vi.unstubAllGlobals());

function respond(body) {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
    vi.stubGlobal('fetch', fetch);
    return fetch;
}

describe('integration catalog and connection contracts', () => {
    it('reads configured connections, excluding model providers', async () => {
        const connection = { id: 'gmail_work', kind: 'integration' };
        const fetch = respond({ connections: [connection, { id: 'llm_openai', kind: 'model_provider' }] });
        expect(await listIntegrationConnections()).toEqual([connection]);
        expect(fetch).toHaveBeenCalledWith('/api/integrations');
    });

    it('does not fall back to legacy data when connections is empty', async () => {
        respond({ connections: [], integrations: [{ id: 'stale' }] });
        expect(await listIntegrationConnections()).toEqual([]);
    });

    it.each([{ integrations: [] }, {}, { connections: null }, { connections: {} }])(
        'rejects a missing or malformed connection array: %j', async (body) => {
            respond(body);
            await expect(listIntegrationConnections()).rejects.toThrow('Invalid integration connection response');
        },
    );

    it('keeps integration definitions under the catalog integrations field', async () => {
        const entries = [{ id: 'gmail', title: 'Gmail' }];
        const fetch = respond({ integrations: entries });
        expect(await listIntegrationCatalog()).toEqual(entries);
        expect(fetch).toHaveBeenCalledWith('/api/integrations/catalog');
    });
});
