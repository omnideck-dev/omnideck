import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SoftwareUpdateStatus from '../SoftwareUpdateStatus.jsx';
import { OmnideckHostProvider } from '../../features/app/OmnideckHost.jsx';

describe('SoftwareUpdateStatus', () => {
    it('links an available version to its app release notes', async () => {
        const host = {
            currentUpdate: vi.fn().mockResolvedValue({ version: '0.5.1', deferred: false }),
            checkForUpdate: vi.fn(),
            installUpdate: vi.fn(),
        };

        await act(async () => {
            render(
                <OmnideckHostProvider host={host}>
                    <SoftwareUpdateStatus />
                </OmnideckHostProvider>,
            );
            await Promise.resolve();
        });

        expect(screen.getByRole('link', { name: /What’s new/ })).toHaveAttribute(
            'href',
            'https://github.com/omnideck-dev/omnideck/releases/tag/app-v0.5.1',
        );
        expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
    });

    it('only claims to be up to date after a successful check and reports failures', async () => {
        const host = {
            currentUpdate: vi.fn().mockResolvedValue(null),
            checkForUpdate: vi.fn().mockResolvedValueOnce(null).mockRejectedValueOnce(new Error('offline')),
        };
        render(<OmnideckHostProvider host={host}><SoftwareUpdateStatus /></OmnideckHostProvider>);
        expect(screen.queryByText('Omnideck is up to date')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
        expect(await screen.findByText('Omnideck is up to date')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
        expect(await screen.findByText('Could not check for updates. Please try again.')).toBeInTheDocument();
        expect(screen.queryByText('Omnideck is up to date')).not.toBeInTheDocument();
    });

    it('follows background updates and ignores an older initial snapshot', async () => {
        let announce;
        let finishSnapshot;
        const unsubscribe = vi.fn();
        const host = {
            currentUpdate: vi.fn(() => new Promise((resolve) => { finishSnapshot = resolve; })),
            onUpdate: vi.fn((listener) => { announce = listener; return unsubscribe; }),
        };
        const { unmount } = render(<OmnideckHostProvider host={host}><SoftwareUpdateStatus /></OmnideckHostProvider>);
        act(() => announce({ version: '0.5.4', deferred: false }));
        await act(async () => { finishSnapshot(null); });
        expect(screen.getByText('Omnideck 0.5.4 is ready')).toBeInTheDocument();
        act(() => announce({ version: '0.5.4', deferred: true }));
        expect(screen.getByText(/Installs the next time/)).toBeInTheDocument();
        act(() => announce(null));
        await waitFor(() => expect(screen.queryByRole('button', { name: 'Update now' })).not.toBeInTheDocument());
        unmount();
        expect(unsubscribe).toHaveBeenCalledOnce();
    });

});
