/**
 * Provider-step UI coverage for the setup wizard.
 *
 * Verifies the conditional-field visibility on step 1: which input
 * fields show up when each provider option is selected, and that the
 * choices and labels come from the server's provider catalog. (The wizard's
 * end-to-end flow is exercised by the autouse e2e fixture; these are
 * focused unit tests so the conditional logic stays covered without
 * needing wizard re-entry, which doesn't exist anymore.)
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { PROVIDER_CATALOG, PROVIDER_CATALOG_WITHOUT_APERTURE } from '../../__tests__/providerCatalogFixture.js';
import useProviderCatalog from '../../hooks/useProviderCatalog.js';
import SetupWizard from '../SetupWizard.jsx';

function _mockFetch({ ollamaHost, providerResponse, catalog = PROVIDER_CATALOG } = {}) {
    return vi.fn((url) => {
        if (url === '/api/providers/catalog') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: catalog }) });
        }
        if (url === '/api/setup/defaults') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ollama_host: ollamaHost ?? null }),
            });
        }
        if (url === '/api/integrations') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ connections: [] }) });
        }
        if (url === '/api/providers') {
            return Promise.resolve(providerResponse ?? { ok: true, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
}

function WizardWithCatalog(props) {
    const providerCatalog = useProviderCatalog();
    return <SetupWizard providerCatalog={providerCatalog} {...props} />;
}

async function _advanceToProviderStep() {
    // Step 0 is the welcome; clicking "Get Started" advances to the provider step.
    fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));
    await screen.findByText('Choose your LLM provider');
    await screen.findByText('Ollama');
}

describe('SetupWizard provider-step field visibility', () => {
    beforeEach(() => {
        globalThis.fetch = _mockFetch();
    });

    it('shows only the Ollama URL field when Ollama is selected', async () => {
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama'));
        });

        expect(container.querySelector('#ollama-url')).toBeInTheDocument();
        expect(container.querySelector('#compat-url')).not.toBeInTheDocument();
        expect(container.querySelector('#compat-key')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-provider')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).not.toBeInTheDocument();
    });

    it('prefills the Ollama URL from OLLAMA_HOST setup defaults', async () => {
        globalThis.fetch = _mockFetch({ ollamaHost: 'http://host-gateway:11434' });
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama'));
        });

        expect(await screen.findByDisplayValue('http://host-gateway:11434')).toBeInTheDocument();
        expect(screen.getByText(/Detected automatically/)).toBeInTheDocument();
    });

    it('does not default Ollama to localhost when OLLAMA_HOST is missing', async () => {
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama'));
        });

        const input = screen.getByLabelText('Ollama URL');
        expect(input).toHaveValue('');
        expect(input.getAttribute('placeholder')).not.toContain('localhost');
        expect(input.getAttribute('placeholder')).not.toContain('host.docker.internal');
    });

    it('prompts for a URL and does not probe Ollama when no host is configured', async () => {
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama'));
        });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        });

        expect(await screen.findByRole('alert')).toHaveTextContent('Enter your Ollama server URL to continue.');
        expect(globalThis.fetch).not.toHaveBeenCalledWith('/api/providers', expect.anything());
    });

    it('includes the attempted Ollama URL when the provider probe fails', async () => {
        globalThis.fetch = _mockFetch({
            ollamaHost: 'http://host-gateway:11434',
            providerResponse: {
                ok: false,
                status: 503,
                json: () => Promise.resolve({ message: 'Could not connect to Ollama' }),
            },
        });
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama'));
        });
        await screen.findByDisplayValue('http://host-gateway:11434');
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        });

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'Could not connect to Ollama Tried http://host-gateway:11434.'
        );
    });

    it('shows the URL and optional API key when OpenAI-compatible is selected', async () => {
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('OpenAI-compatible'));
        });

        expect(container.querySelector('#compat-url')).toBeInTheDocument();
        expect(container.querySelector('#compat-key')).toBeInTheDocument();
        expect(container.querySelector('#ollama-url')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-provider')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).not.toBeInTheDocument();
    });

    it('lists the provider choices with catalog labels and descriptions', async () => {
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        const names = Array.from(document.querySelectorAll('[aria-pressed]'))
            .map((card) => card.querySelector('span:not([aria-hidden])').textContent);
        expect(names).toEqual(['Ollama', 'Tailscale Aperture', 'OpenAI-compatible', 'Cloud API']);
        expect(screen.getByText('Run models on your own machine')).toBeInTheDocument();
        expect(screen.getByText('Anthropic, OpenAI, or OpenRouter')).toBeInTheDocument();
    });

    it('hides Aperture when the catalog does not list it', async () => {
        globalThis.fetch = _mockFetch({ catalog: PROVIDER_CATALOG_WITHOUT_APERTURE });
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        expect(screen.queryByText('Tailscale Aperture')).not.toBeInTheDocument();
        expect(screen.getByText('Ollama')).toBeInTheDocument();
    });

    it('asks Aperture for only its gateway URL', async () => {
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Tailscale Aperture'));
        });

        expect(screen.getByLabelText('Gateway URL')).toBeInTheDocument();
        expect(screen.getByText(/Tailscale provides identity/)).toBeInTheDocument();
        expect(container.querySelector('#compat-key')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).not.toBeInTheDocument();
    });

    it('posts an Aperture direct-provider connection with no API key', async () => {
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        fireEvent.click(screen.getByText('Tailscale Aperture'));
        fireEvent.change(screen.getByLabelText('Gateway URL'), {
            target: { value: 'http://aperture.example.ts.net' },
        });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            method: 'POST',
            body: JSON.stringify({
                name: 'aperture',
                base_url: 'http://aperture.example.ts.net',
            }),
        }));
    });

    it('shows the provider select and API key when Cloud API is selected', async () => {
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Cloud API'));
        });

        expect(container.querySelector('#cloud-provider')).toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).toBeInTheDocument();
        expect(container.querySelector('#ollama-url')).not.toBeInTheDocument();
        expect(container.querySelector('#compat-url')).not.toBeInTheDocument();
        expect(container.querySelector('#compat-key')).not.toBeInTheDocument();
    });

    it('Cloud API offers the catalog providers that need a key, in catalog order', async () => {
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Cloud API'));
        });

        expect(screen.getByLabelText('API Key')).toHaveAttribute('placeholder', 'sk-ant-...');
        fireEvent.click(container.querySelector('#cloud-provider'));
        const options = screen.getAllByRole('option');
        expect(options.map((option) => option.dataset.value)).toEqual(['anthropic', 'openai', 'openrouter']);
        ['Anthropic', 'OpenAI', 'OpenRouter'].forEach((label, i) => expect(options[i]).toHaveTextContent(label));
    });

    it('builds the cloud choices from whatever the catalog lists', async () => {
        globalThis.fetch = _mockFetch({
            catalog: PROVIDER_CATALOG.filter((c) => c.name !== 'anthropic'),
        });
        const { container } = render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        expect(screen.getByText('OpenAI or OpenRouter')).toBeInTheDocument();
        await act(async () => {
            fireEvent.click(screen.getByText('Cloud API'));
        });

        fireEvent.click(container.querySelector('#cloud-provider'));
        const values = screen.getAllByRole('option').map((option) => option.dataset.value);
        expect(values).toEqual(['openai', 'openrouter']);
        fireEvent.change(screen.getByLabelText('API Key'), { target: { value: 'sk-test' } });
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            body: JSON.stringify({ name: 'openai', api_key: 'sk-test' }),
        }));
    });

    it('sends the catalog URL hint when the OpenAI-compatible URL is left blank', async () => {
        render(<WizardWithCatalog onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('OpenAI-compatible'));
        });
        expect(screen.getByLabelText('Server URL')).toHaveAttribute('placeholder', 'http://localhost:1234/v1');
        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
        });

        expect(globalThis.fetch).toHaveBeenCalledWith('/api/providers', expect.objectContaining({
            body: JSON.stringify({ name: 'openai_compat', base_url: 'http://localhost:1234/v1' }),
        }));
    });
});
