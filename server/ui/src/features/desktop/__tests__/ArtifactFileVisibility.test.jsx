import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';

import DesktopViewContent from '../DesktopViewContent.jsx';
import { _reset as resetFileWatch } from '../../../utils/fileWatchStore.js';

afterEach(() => {
    cleanup();
    resetFileWatch();
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

it('keeps an artifact preview mounted while its desktop tab stops watching the file', async () => {
    vi.useFakeTimers();
    let etag = 'v1';
    const fetchMock = vi.fn(async () => ({
        ok: true,
        text: async () => 'Report content',
        headers: { get: (name) => name === 'ETag' ? etag : null },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const view = {
        type: 'artifact-file',
        artifact: {
            filename: 'report.md',
            content_type: 'text/markdown',
            path: '/home/omnideck/report.md',
        },
    };
    const rendered = render(<DesktopViewContent view={view} visible />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const preview = screen.getByText('Report content');
    const heads = () => fetchMock.mock.calls.filter(([, options]) => options?.method === 'HEAD');
    expect(heads()).toHaveLength(1);

    rendered.rerender(<DesktopViewContent view={view} visible={false} />);
    etag = 'v2';
    await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
    expect(heads()).toHaveLength(1);
    expect(screen.getByText('Report content')).toBe(preview);

    rendered.rerender(<DesktopViewContent view={view} visible />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(heads()).toHaveLength(2);
    expect(screen.getByText('Report content')).toBe(preview);
    expect(screen.getByTitle(/changed on disk/i)).toBeInTheDocument();
});
