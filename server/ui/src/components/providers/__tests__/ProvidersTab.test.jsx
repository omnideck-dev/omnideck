/**
 * Coverage for the brokered-provider base URL edit affordance (DetailPane).
 *
 * Before this fix, a brokered provider's edit pane only exposed the API
 * key — the base_url the backend already accepted was never sent, so a
 * mistyped OpenAI-compatible endpoint couldn't be corrected from the UI.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import ProvidersTab from '../ProvidersTab.jsx';

const refresh = vi.fn();

function _mockAppData(providers) {
    vi.doMock('../../../contexts/AppData.jsx', () => ({
        useAppData: () => ({
            providersHook: { providers, loading: false, error: null, refresh },
        }),
    }));
}

function _mockFetch(handlers = {}) {
    globalThis.fetch = vi.fn((url) => {
        for (const [pattern, respond] of Object.entries(handlers)) {
            if (url.includes(pattern)) return respond();
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
    });
}

describe('ProvidersTab brokered base URL', () => {
    it('shows a read-only value for a brokered provider with a stored base_url', async () => {
        vi.resetModules();
        _mockAppData([{
            name: 'openai_compat', kind: 'brokered', status: 'running',
            base_url: 'https://my-proxy.example.com/v1',
        }]);
        _mockFetch();
        const { default: FreshProvidersTab } = await import('../ProvidersTab.jsx');
        await act(async () => { render(<FreshProvidersTab />); });

        expect(screen.getByTestId('provider-base-url-value')).toHaveTextContent(
            'https://my-proxy.example.com/v1',
        );
        expect(screen.queryByTestId('provider-base-url-input')).not.toBeInTheDocument();
    });

    it('does not prefill the API Key field with the stored base_url', async () => {
        // A brokered provider's base_url is now returned by GET /api/providers
        // for display — it must not leak into the (visually masked) API Key
        // input's initial value, since that field represents a secret.
        vi.resetModules();
        _mockAppData([{
            name: 'openai_compat', kind: 'brokered', status: 'running',
            base_url: 'https://my-proxy.example.com/v1',
        }]);
        _mockFetch();
        const { default: FreshProvidersTab } = await import('../ProvidersTab.jsx');
        await act(async () => { render(<FreshProvidersTab />); });

        const keyInput = document.querySelector('input[type="password"]');
        expect(keyInput).toHaveValue('');
    });

    it('hides the base URL section for a brokered provider with no base_url use case', async () => {
        vi.resetModules();
        _mockAppData([{ name: 'anthropic', kind: 'brokered', status: 'running', base_url: null }]);
        _mockFetch();
        const { default: FreshProvidersTab } = await import('../ProvidersTab.jsx');
        await act(async () => { render(<FreshProvidersTab />); });

        expect(screen.queryByTestId('provider-base-url-value')).not.toBeInTheDocument();
    });

    it('editing the URL and saving sends both api_key and base_url in the PATCH body', async () => {
        vi.resetModules();
        _mockAppData([{
            name: 'openai_compat', kind: 'brokered', status: 'running',
            base_url: 'https://old-proxy.example.com/v1',
        }]);
        let patchBody = null;
        globalThis.fetch = vi.fn((url, opts) => {
            if (url === '/api/providers/openai_compat' && opts?.method === 'PATCH') {
                patchBody = JSON.parse(opts.body);
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        provider: { name: 'openai_compat', kind: 'brokered', status: 'connected' },
                        models: [],
                    }),
                });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
        });

        const { default: FreshProvidersTab } = await import('../ProvidersTab.jsx');
        await act(async () => { render(<FreshProvidersTab />); });

        await act(async () => {
            fireEvent.click(screen.getByTestId('provider-base-url-edit-btn'));
        });
        fireEvent.change(screen.getByTestId('provider-base-url-input'), {
            target: { value: 'https://new-proxy.example.com/v1' },
        });
        const keyInput = document.querySelector('input[type="password"]');
        fireEvent.change(keyInput, { target: { value: 'sk-rotated' } });
        await act(async () => {
            fireEvent.click(screen.getByText('Save'));
        });

        expect(patchBody).toEqual({
            api_key: 'sk-rotated',
            base_url: 'https://new-proxy.example.com/v1',
        });
    });
});
