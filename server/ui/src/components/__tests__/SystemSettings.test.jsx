import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import SystemSettings from '../SystemSettings.jsx';
import { OmnideckHostProvider } from '../../features/app/OmnideckHost.jsx';

const refreshFeatures = vi.fn();
const providersHook = { providers: [] };

vi.mock('../../contexts/AppData.jsx', () => ({
    useAppData: () => ({ providersHook, refreshFeatures }),
}));

describe('SystemSettings', () => {
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
                        custom_tools_enabled: true,
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
                        custom_tools_enabled: false,
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
            render(
                <OmnideckHostProvider host={null}>
                    <SystemSettings />
                </OmnideckHostProvider>,
            );
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

    it('persists Custom Tools and refreshes shell feature state', async () => {
        await act(async () => {
            render(
                <OmnideckHostProvider host={null}>
                    <SystemSettings />
                </OmnideckHostProvider>,
            );
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        const toggle = await screen.findByRole('switch', { name: 'Custom Tools' });
        expect(screen.getByText(/The agent can create, save, and run reusable tools/)).toBeInTheDocument();
        expect(toggle).not.toBeChecked();
        await act(async () => {
            fireEvent.click(toggle);
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledWith(
            '/api/settings',
            expect.objectContaining({
                method: 'PUT',
                body: JSON.stringify({ custom_tools_enabled: true }),
            }),
        ));
        await waitFor(() => expect(refreshFeatures).toHaveBeenCalledOnce());
        expect(toggle).toBeChecked();
    });

    it('groups related settings while keeping model pickers distinct', async () => {
        const host = {
            currentUpdate: vi.fn().mockResolvedValue(null),
            checkForUpdate: vi.fn().mockResolvedValue(null),
            installUpdate: vi.fn().mockResolvedValue(undefined),
        };

        await act(async () => {
            render(
                <OmnideckHostProvider host={host}>
                    <SystemSettings />
                </OmnideckHostProvider>,
            );
            await new Promise((resolve) => setTimeout(resolve, 0));
        });

        const updates = await screen.findByTestId('updates-settings-group');
        expect(within(updates).getByText('Omnideck is up to date')).toBeInTheDocument();
        expect(within(updates).getByRole('switch', { name: 'Install updates automatically' })).toBeInTheDocument();

        const experimental = screen.getByTestId('experimental-settings-group');
        expect(within(experimental).getByRole('switch', { name: 'Apps' })).toBeInTheDocument();
        expect(within(experimental).getByRole('switch', { name: 'Custom Tools' })).toBeInTheDocument();

        const models = screen.getByTestId('model-defaults-group');
        expect(within(models).getByText('Vision')).toBeInTheDocument();
        expect(within(models).getByText('Compaction')).toBeInTheDocument();
        expect(within(models).getByText('Title generation')).toBeInTheDocument();
        expect(within(models).getAllByTestId('model-picker')).toHaveLength(3);
    });
});
