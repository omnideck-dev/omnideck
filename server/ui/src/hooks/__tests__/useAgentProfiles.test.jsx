import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import useAgentProfiles from '../useAgentProfiles.js';

afterEach(() => vi.unstubAllGlobals());

it('keeps a rejected new agent out of the list and allows creation to be retried', async () => {
    const created = { id: 'new-agent', name: 'Research', model: 'test-model' };
    const fetchMock = vi.fn()
        .mockResolvedValueOnce({ ok: true, json: async () => [] })
        .mockResolvedValueOnce({ ok: false, json: async () => ({ message: 'Model unavailable' }) })
        .mockResolvedValueOnce({ ok: true, json: async () => created });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useAgentProfiles());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
        await expect(result.current.createProfile(created)).rejects.toThrow('Model unavailable');
    });
    expect(result.current.profiles).toEqual([]);
    expect(result.current.revision).toBe(0);
    await act(async () => {
        await expect(result.current.createProfile(created)).resolves.toEqual(created);
    });
    expect(result.current.profiles).toEqual([created]);
    expect(result.current.revision).toBe(1);
});
