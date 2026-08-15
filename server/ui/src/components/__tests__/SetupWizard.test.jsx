/**
 * Provider-step UI coverage for the setup wizard.
 *
 * Verifies the conditional-field visibility on step 1: which input
 * fields show up when each provider option is selected. (The wizard's
 * end-to-end flow is exercised by the autouse e2e fixture; these are
 * focused unit tests so the conditional logic stays covered without
 * needing wizard re-entry, which doesn't exist anymore.)
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import SetupWizard from '../SetupWizard.jsx';

function _mockFetch({ ollamaHost, providerResponse } = {}) {
    return vi.fn((url) => {
        if (url === '/api/setup/defaults') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ollama_host: ollamaHost ?? null }),
            });
        }
        if (url === '/api/integrations') {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ integrations: [] }) });
        }
        if (url === '/api/providers') {
            return Promise.resolve(providerResponse ?? { ok: true, json: () => Promise.resolve({}) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
}

async function _advanceToProviderStep() {
    // Step 0 is the welcome; clicking "Get Started" advances to the provider step.
    fireEvent.click(screen.getByRole('button', { name: 'Get Started' }));
    await screen.findByText('Choose your LLM provider');
}

describe('SetupWizard provider-step field visibility', () => {
    beforeEach(() => {
        globalThis.fetch = _mockFetch();
    });

    it('shows only the Ollama URL field when Ollama is selected', async () => {
        const { container } = render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama (local)'));
        });

        expect(container.querySelector('#ollama-url')).toBeInTheDocument();
        expect(container.querySelector('#compat-url')).not.toBeInTheDocument();
        expect(container.querySelector('#compat-key')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-provider')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).not.toBeInTheDocument();
    });

    it('prefills the Ollama URL from OLLAMA_HOST setup defaults', async () => {
        globalThis.fetch = _mockFetch({ ollamaHost: 'http://host-gateway:11434' });
        render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama (local)'));
        });

        expect(await screen.findByDisplayValue('http://host-gateway:11434')).toBeInTheDocument();
        expect(screen.getByText(/Detected automatically/)).toBeInTheDocument();
    });

    it('does not default Ollama to localhost when OLLAMA_HOST is missing', async () => {
        render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama (local)'));
        });

        const input = screen.getByLabelText('Ollama URL');
        expect(input).toHaveValue('');
        expect(input.getAttribute('placeholder')).not.toContain('localhost');
        expect(input.getAttribute('placeholder')).not.toContain('host.docker.internal');
    });

    it('prompts for a URL and does not probe Ollama when no host is configured', async () => {
        render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama (local)'));
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
        render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Ollama (local)'));
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
        const { container } = render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('OpenAI-compatible endpoint'));
        });

        expect(container.querySelector('#compat-url')).toBeInTheDocument();
        expect(container.querySelector('#compat-key')).toBeInTheDocument();
        expect(container.querySelector('#ollama-url')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-provider')).not.toBeInTheDocument();
        expect(container.querySelector('#cloud-key')).not.toBeInTheDocument();
    });

    it('shows the provider select and API key when Cloud API is selected', async () => {
        const { container } = render(<SetupWizard onComplete={vi.fn()} />);
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

    it('Cloud API offers Anthropic, OpenAI, and OpenRouter as choices', async () => {
        const { container } = render(<SetupWizard onComplete={vi.fn()} />);
        await _advanceToProviderStep();

        await act(async () => {
            fireEvent.click(screen.getByText('Cloud API'));
        });

        fireEvent.click(container.querySelector('#cloud-provider'));
        const values = screen.getAllByRole('option').map((option) => option.dataset.value);
        expect(values).toEqual(['anthropic', 'openai', 'openrouter']);
    });
});
