/**
 * Configure-step coverage for the add-provider modal.
 *
 * Focus: the Ollama base URL is prefilled from the host detected at
 * install time (GET /api/setup/defaults) rather than a hardcoded default,
 * so the user doesn't have to guess an address from their container runtime.
 */

import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

import AddProviderModal from '../AddProviderModal.jsx';

function _mockFetch({ ollamaHost } = {}) {
    return vi.fn((url) => {
        if (url === '/api/setup/defaults') {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ ollama_host: ollamaHost ?? null }),
            });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
}

async function _openConfigure(name) {
    await act(async () => {
        fireEvent.click(screen.getByTestId(`provider-catalog-card-${name}`));
    });
    await act(async () => {
        fireEvent.click(screen.getByTestId('provider-catalog-continue-btn'));
    });
}

describe('AddProviderModal Ollama host prefill', () => {
    it('portals outside a clipping provider view', () => {
        globalThis.fetch = _mockFetch();
        const { container } = render(
            <div style={{ overflow: 'hidden' }}>
                <AddProviderModal onClose={vi.fn()} onAdded={vi.fn()} />
            </div>,
        );

        expect(container).not.toContainElement(screen.getByTestId('add-provider-modal'));
        expect(document.body).toContainElement(screen.getByTestId('add-provider-modal'));
    });

    it('prefills the base URL from the detected host', async () => {
        globalThis.fetch = _mockFetch({ ollamaHost: 'http://host-gateway:11434' });
        render(<AddProviderModal onClose={vi.fn()} onAdded={vi.fn()} />);
        await _openConfigure('ollama');

        expect(await screen.findByDisplayValue('http://host-gateway:11434')).toBeInTheDocument();
        expect(screen.getByText('Detected automatically.')).toBeInTheDocument();
    });

    it('leaves the base URL empty with no hardcoded default when no host is detected', async () => {
        globalThis.fetch = _mockFetch();
        render(<AddProviderModal onClose={vi.fn()} onAdded={vi.fn()} />);
        await _openConfigure('ollama');

        const input = document.querySelector('#provider-url');
        expect(input).toHaveValue('');
        expect(input.getAttribute('placeholder')).not.toContain('host.docker.internal');
        expect(input.getAttribute('placeholder')).not.toContain('localhost');
    });
});

describe('AddProviderModal Aperture setup', () => {
    it('asks only for the gateway URL and discovers the connection', async () => {
        globalThis.fetch = _mockFetch();
        render(<AddProviderModal onClose={vi.fn()} onAdded={vi.fn()} />);
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
