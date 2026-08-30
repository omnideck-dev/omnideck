import { afterEach, describe, expect, it, vi } from 'vitest';

import { BrowserRequestError, deleteBrowserProfile } from '../browserApi.js';

describe('browserApi', () => {
    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('preserves structured error details returned by the server', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
            error: 'This browser profile is assigned to an agent',
            agents: ['Recruiting', 'LinkedIn Outreach'],
        }), {
            status: 409,
            headers: { 'Content-Type': 'application/json' },
        })));

        await expect(deleteBrowserProfile('linkedin')).rejects.toMatchObject({
            name: 'BrowserRequestError',
            message: 'This browser profile is assigned to an agent',
            status: 409,
            details: {
                agents: ['Recruiting', 'LinkedIn Outreach'],
            },
        });

        expect(fetch).toHaveBeenCalledWith('/api/browser/profiles/linkedin', {
            method: 'DELETE',
        });
        expect(BrowserRequestError).toBeTypeOf('function');
    });
});
