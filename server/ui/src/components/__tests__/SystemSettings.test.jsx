import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SystemSettings from '../SystemSettings.jsx';

const refreshFeatures = vi.fn();
const providersHook = { providers: [] };

vi.mock('../../contexts/AppData.jsx', () => ({
    useAppData: () => ({ providersHook, refreshFeatures }),
}));

describe('SystemSettings custom apps toggle', () => {
    beforeEach(() => {
        refreshFeatures.mockReset();
        globalThis.fetch = vi.fn((url, init = {}) => {
            if (url === '/api/settings' && init.method === 'PUT') {
                return Promise.resolve({
                    ok: true,
                    json: async () => ({
                        setup_complete: true,
                        default_agent: 'omnideck',
                        custom_apps_enabled: true,
                    }),
                });
            }
            if (url === '/api/settings') {
                return Promise.resolve({
                    ok: true,
                    json: async () => ({
                        setup_complete: true,
                        default_agent: 'omnideck',
                        custom_apps_enabled: false,
                    }),
                });
            }
            if (url === '/api/profiles') {
                return Promise.resolve({
                    ok: true,
                    json: async () => [{ id: 'omnideck', name: 'Omnideck' }],
                });
            }
            return Promise.resolve({ ok: true, json: async () => ({}) });
        });
    });

    it('persists Apps and refreshes shell feature state', async () => {
        await act(async () => {
            render(<SystemSettings />);
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        const toggle = await screen.findByRole('switch', { name: 'Apps' });
        expect(screen.getByText(/Apps let your Omnideck agents build and run personalized tools/)).toBeInTheDocument();
        expect(screen.getByText(/Backward compatibility is not guaranteed/)).toBeInTheDocument();
        expect(toggle).not.toBeChecked();
        await act(async () => {
            fireEvent.click(toggle);
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
            '/api/settings',
            expect.objectContaining({
                method: 'PUT',
                body: JSON.stringify({ custom_apps_enabled: true }),
            }),
        ));
        await waitFor(() => expect(refreshFeatures).toHaveBeenCalledOnce());
        expect(toggle).toBeChecked();
    });
});
