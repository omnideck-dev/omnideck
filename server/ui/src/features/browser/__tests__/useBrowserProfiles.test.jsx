import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import useBrowserProfiles from '../useBrowserProfiles.js';

const mocks = vi.hoisted(() => ({
    listBrowserProfiles: vi.fn(),
}));

vi.mock('../browserApi.js', () => ({
    listBrowserProfiles: mocks.listBrowserProfiles,
}));

describe('useBrowserProfiles', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('keeps Default first and sorts catalog mutations by profile name', async () => {
        mocks.listBrowserProfiles.mockResolvedValue([
            { id: 'zebra', name: 'Zebra' },
            { id: 'default', name: 'Default' },
        ]);
        const { result } = renderHook(() => useBrowserProfiles());

        await waitFor(() => expect(result.current.loaded).toBe(true));
        act(() => result.current.upsertProfile({ id: 'alpha', name: 'alpha' }));

        expect(result.current.profiles.map((profile) => profile.id)).toEqual([
            'default',
            'alpha',
            'zebra',
        ]);
    });

    it('can retry after the initial catalog request fails', async () => {
        mocks.listBrowserProfiles
            .mockRejectedValueOnce(new Error('Offline'))
            .mockResolvedValueOnce([{ id: 'default', name: 'Default' }]);
        const { result } = renderHook(() => useBrowserProfiles());

        await waitFor(() => expect(result.current.error?.message).toBe('Offline'));
        await act(async () => {
            await result.current.refresh({ force: true });
        });

        expect(result.current.error).toBeNull();
        expect(result.current.loaded).toBe(true);
        expect(result.current.profiles).toEqual([{ id: 'default', name: 'Default' }]);
    });
});
