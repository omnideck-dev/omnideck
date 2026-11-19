/**
 * Coverage for the add-provider modal.
 *
 * The picker and the configure form both come from the server's provider
 * catalog: the cards list its entries in order, and each entry's base_url
 * and api_key values decide which fields the form shows.
 */

import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import { PROVIDER_CATALOG, PROVIDER_CATALOG_WITHOUT_APERTURE } from '../../../__tests__/providerCatalogFixture.js';
import useProviderCatalog from '../../../hooks/useProviderCatalog.js';
import AddProviderModal from '../AddProviderModal.jsx';

function _mockFetch({ ollamaHost, catalog = PROVIDER_CATALOG, catalogResponse } = {}) {
    return vi.fn((url) => {
        if (url === '/api/setup/defaults') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ollama_host: ollamaHost ?? null }),
            });
        }
        if (url === '/api/providers/catalog') {
            return Promise.resolve(catalogResponse ?? {
                ok: true,
                json: () => Promise.resolve({ providers: catalog }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
}

function ModalWithCatalog(props) {
    const providerCatalog = useProviderCatalog();
    return <AddProviderModal providerCatalog={providerCatalog} onClose={vi.fn()} onAdded={vi.fn()} {...props} />;
}

async function _renderModal(props) {
    const view = render(<ModalWithCatalog {...props} />);
    await screen.findAllByTestId(/^provider-catalog-card-/);
    return view;
}

async function _openConfigure(name) {
    await act(async () => {
        fireEvent.click(screen.getByTestId(`provider-catalog-card-${name}`));
    });
    await act(async () => {
        fireEvent.click(screen.getByTestId('provider-catalog-continue-btn'));
    });
}

function _cardNames() {
    return screen.getAllByTestId(/^provider-catalog-card-/)
        .map((card) => card.dataset.testid.replace('provider-catalog-card-', ''));
}

describe('AddProviderModal catalog step', () => {
    it('portals outside a clipping provider view', async () => {
        globalThis.fetch = _mockFetch();
        const { container } = render(
            <div style={{ overflow: 'hidden' }}>
                <ModalWithCatalog />
            </div>,
        );
        await screen.findByTestId('provider-catalog-card-ollama');

        expect(container).not.toContainElement(screen.getByTestId('add-provider-modal'));
        expect(document.body).toContainElement(screen.getByTestId('add-provider-modal'));
    });

    it('lists exactly the catalog entries in catalog order', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();

        expect(_cardNames()).toEqual(PROVIDER_CATALOG.map((c) => c.name));
        const card = screen.getByTestId('provider-catalog-card-openrouter');
        expect(within(card).getByText('OpenRouter')).toBeInTheDocument();
        expect(within(card).getByText('Many providers, one API')).toBeInTheDocument();
        expect(card.querySelector('.bi-router')).toBeInTheDocument();
    });

    it('leaves out Aperture when the catalog does not list it', async () => {
        globalThis.fetch = _mockFetch({ catalog: PROVIDER_CATALOG_WITHOUT_APERTURE });
        await _renderModal();

        expect(_cardNames()).toEqual(['ollama', 'openai_compat', 'anthropic', 'openai', 'openrouter']);
    });

    it('leaves out providers that are already configured', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal({ existingNames: ['ollama', 'anthropic'] });

        expect(_cardNames()).toEqual(['aperture', 'openai_compat', 'openai', 'openrouter']);
    });

    it('offers a retry when the catalog fails to load', async () => {
        globalThis.fetch = _mockFetch({
            catalogResponse: { ok: false, status: 500, json: () => Promise.resolve({ error: 'Catalog unavailable' }) },
        });
        render(<ModalWithCatalog />);

        expect(await screen.findByText("Couldn't load providers")).toBeInTheDocument();
        expect(screen.queryByText('All providers configured')).not.toBeInTheDocument();

        globalThis.fetch = _mockFetch();
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /Retry/ }));
        });
        expect(await screen.findByTestId('provider-catalog-card-ollama')).toBeInTheDocument();
    });
});

describe('AddProviderModal configure fields', () => {
    it('shows only a required URL when the entry takes no key', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();
        await _openConfigure('ollama');

        expect(document.querySelector('#provider-url')).toBeInTheDocument();
        expect(document.querySelector('#provider-key')).not.toBeInTheDocument();
        expect(screen.getByTestId('provider-configure-submit-btn')).toBeDisabled();
    });

    it('shows a required URL and an optional key with the catalog URL hint', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();
        await _openConfigure('openai_compat');

        const url = document.querySelector('#provider-url');
        expect(url).toHaveAttribute('placeholder', 'http://localhost:1234/v1');
        expect(screen.getByLabelText('API Key (optional)')).toBeInTheDocument();
        expect(screen.getByTestId('provider-configure-submit-btn')).toBeDisabled();

        fireEvent.change(url, { target: { value: 'http://gpu-box:8000/v1' } });
        expect(screen.getByTestId('provider-configure-submit-btn')).toBeEnabled();
        await act(async () => {
            fireEvent.click(screen.getByTestId('provider-configure-submit-btn'));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ name: 'openai_compat', base_url: 'http://gpu-box:8000/v1' }),
        }));
    });

    it('shows only a required key with the catalog key hint when the entry takes no URL', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();
        await _openConfigure('openrouter');

        expect(document.querySelector('#provider-url')).not.toBeInTheDocument();
        const key = screen.getByLabelText('API Key');
        expect(key).toHaveAttribute('placeholder', 'sk-or-v1-...');
        expect(screen.getByTestId('provider-configure-submit-btn')).toBeDisabled();

        fireEvent.change(key, { target: { value: 'sk-or-v1-test' } });
        await act(async () => {
            fireEvent.click(screen.getByTestId('provider-configure-submit-btn'));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({ name: 'openrouter', api_key: 'sk-or-v1-test' }),
        }));
    });
});

describe('AddProviderModal Ollama host prefill', () => {
    it('prefills the base URL from the detected host', async () => {
        globalThis.fetch = _mockFetch({ ollamaHost: 'http://host-gateway:11434' });
        await _renderModal();
        await _openConfigure('ollama');

        expect(await screen.findByDisplayValue('http://host-gateway:11434')).toBeInTheDocument();
        expect(screen.getByText('Detected automatically.')).toBeInTheDocument();
    });

    it('leaves the base URL empty with no hardcoded default when no host is detected', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();
        await _openConfigure('ollama');

        await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith('/api/setup/defaults'));
        const input = document.querySelector('#provider-url');
        expect(input).toHaveValue('');
        expect(input.getAttribute('placeholder')).not.toContain('host.docker.internal');
        expect(input.getAttribute('placeholder')).not.toContain('localhost');
    });
});

describe('AddProviderModal Aperture setup', () => {
    it('asks only for the gateway URL and discovers the connection', async () => {
        globalThis.fetch = _mockFetch();
        await _renderModal();
        await _openConfigure('aperture');

        expect(screen.getByText('Tailscale handles access')).toBeInTheDocument();
        expect(screen.getByLabelText('Gateway URL')).toBeInTheDocument();
        expect(document.querySelector('#provider-key')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: /Discover & add/ })).toBeDisabled();

        fireEvent.change(screen.getByLabelText('Gateway URL'), {
            target: { value: 'http://aperture.example.ts.net/ui/' },
        });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: /Discover & add/ }));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({
                name: 'aperture',
                base_url: 'http://aperture.example.ts.net/ui/',
            }),
        }));
    });
});
