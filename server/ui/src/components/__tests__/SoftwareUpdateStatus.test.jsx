import { act, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SoftwareUpdateStatus from '../SoftwareUpdateStatus.jsx';
import { OmnideckHostProvider } from '../../features/app/OmnideckHost.jsx';

describe('SoftwareUpdateStatus', () => {
    it('links an available version to its app release notes', async () => {
        const host = {
            currentUpdate: vi.fn().mockResolvedValue({ version: '0.2.1', deferred: false }),
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
            'https://github.com/omnideck-dev/omnideck/blob/main/docs/releases/app-v0.2.1.md',
        );
        expect(screen.getByRole('button', { name: 'Update now' })).toBeInTheDocument();
    });
});
