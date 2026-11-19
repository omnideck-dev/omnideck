import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { catalogHook, PROVIDER_CATALOG_WITHOUT_APERTURE } from '../../../__tests__/providerCatalogFixture.js';
import { useAppData } from '../../../contexts/AppData.jsx';
import rowStyles from '../../ListItem.module.css';
import buttonStyles from '../../primitives/Button.module.css';
import confirmStyles from '../../primitives/ConfirmButton.module.css';
import ProvidersTab from '../ProvidersTab.jsx';

vi.mock('../../../contexts/AppData.jsx', () => ({ useAppData: vi.fn() }));

beforeEach(() => {
    useAppData.mockReturnValue({
        providersHook: {
            providers: [{ name: 'ollama', label: 'Ollama', kind: 'direct', status: 'configured', base_url: 'http://localhost:11434' }],
            loading: false, refresh: vi.fn(),
        },
        providerCatalogHook: catalogHook(),
    });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
        ok: true, json: async () => ({ models: [{ id: 'test-model' }] }),
    }));
});
afterEach(() => vi.unstubAllGlobals());

describe('ProvidersTab shared presentation', () => {
    it('uses shared rows and quiet Add, without duplicating healthy status in the list', async () => {
        render(<ProvidersTab />);
        const row = screen.getByTestId('provider-row-ollama');
        await waitFor(() => expect(row).toHaveTextContent('1 model'));
        expect(row).toHaveClass(rowStyles.item, rowStyles.active);
        expect(row).toHaveAttribute('aria-current', 'true');
        expect(row).not.toHaveTextContent(/configured|connected/i);
        expect(screen.getByTestId('providers-add-btn')).toHaveClass(buttonStyles.btn, buttonStyles.ghost);
        expect(screen.getByTestId('provider-status')).toHaveTextContent('Configured');
        expect(screen.getByTestId('provider-status').querySelector('.bi-check-lg')).toHaveAttribute('aria-hidden', 'true');
    });

    it('uses the same healthy status after a connection test', async () => {
        render(<ProvidersTab />);
        fireEvent.click(screen.getByTestId('provider-test-btn'));
        await waitFor(() => expect(screen.getByTestId('provider-status')).toHaveTextContent('Connected'));
        expect(screen.getByTestId('provider-row-ollama')).not.toHaveTextContent('Connected');
    });

    it('keeps connection failures visible in both the list and details', async () => {
        fetch.mockResolvedValue({ ok: false, json: async () => ({ message: 'Unavailable' }) });
        render(<ProvidersTab />);
        expect(await within(screen.getByTestId('provider-row-ollama')).findByText("Couldn't connect")).toBeVisible();
        expect(screen.getByTestId('provider-status')).toHaveTextContent("Couldn't connect");
        expect(screen.getByTestId('provider-status').querySelector('.bi-check-lg')).toBeNull();
    });

    it('uses the shared destructive confirmation without page overrides', async () => {
        render(<ProvidersTab />);
        await within(screen.getByTestId('provider-row-ollama')).findByText('1 model');
        const remove = screen.getByTestId('provider-remove-btn');
        expect(remove.className).toBe(confirmStyles.btn);
        fireEvent.click(remove);
        expect(remove).toHaveTextContent('Confirm remove?');
        expect(remove).toHaveClass(confirmStyles.confirming);
        expect(fetch).not.toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ method: 'DELETE' }));
    });
});

describe('ProvidersTab catalog labels and icons', () => {
    it('labels rows from the provider list and takes icons from the catalog', async () => {
        useAppData.mockReturnValue({
            providersHook: {
                providers: [
                    { name: 'openrouter', label: 'OpenRouter', kind: 'brokered', status: 'running' },
                    { name: 'aperture', label: 'Tailscale Aperture', kind: 'direct', status: 'configured', base_url: 'http://ai.example.ts.net' },
                ],
                loading: false, refresh: vi.fn(),
            },
            providerCatalogHook: catalogHook(PROVIDER_CATALOG_WITHOUT_APERTURE),
        });
        render(<ProvidersTab />);

        const openrouter = screen.getByTestId('provider-row-openrouter');
        expect(openrouter).toHaveTextContent('OpenRouter');
        expect(openrouter.querySelector('.bi-router')).toBeInTheDocument();
        expect(within(screen.getByTestId('provider-detail')).getByText('OpenRouter')).toBeInTheDocument();

        // A kind the catalog leaves out keeps its server label and gets the generic icon.
        const aperture = screen.getByTestId('provider-row-aperture');
        expect(aperture).toHaveTextContent('Tailscale Aperture');
        expect(aperture.querySelector('.bi-plug')).toBeInTheDocument();
        await waitFor(() => expect(openrouter).toHaveTextContent('1 model'));
    });

    it('opens the add modal with the catalog entries not yet configured', async () => {
        render(<ProvidersTab />);
        fireEvent.click(screen.getByTestId('providers-add-btn'));

        const cards = screen.getAllByTestId(/^provider-catalog-card-/)
            .map((card) => card.dataset.testid.replace('provider-catalog-card-', ''));
        expect(cards).toEqual(['aperture', 'openai_compat', 'anthropic', 'openai', 'openrouter']);
        await within(screen.getByTestId('provider-row-ollama')).findByText('1 model');
    });
});
