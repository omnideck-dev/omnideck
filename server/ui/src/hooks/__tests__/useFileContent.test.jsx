import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useFileContent from '../useFileContent.js';

// Captures the hook's latest return value so assertions can read it between acts.
let latest;
function Harness({ item }) {
    latest = useFileContent(item);
    return null;
}

function makeResponse({ etag, body = '' }) {
    return {
        ok: true,
        text: async () => body,
        headers: { get: (h) => (h.toLowerCase() === 'etag' ? etag : null) },
    };
}

let currentEtag;

beforeEach(() => {
    vi.useFakeTimers();
    currentEtag = 'v1';
    global.fetch = vi.fn((url, opts) => {
        const isHead = opts && opts.method === 'HEAD';
        return Promise.resolve(
            makeResponse({ etag: currentEtag, body: isHead ? '' : `body@${currentEtag}` }),
        );
    });
});

afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    latest = undefined;
});

const textItem = {
    filename: 'analysis.md',
    content_type: 'text/markdown',
    path: '/home/user/analysis.md',
};

describe('useFileContent disk-change watcher', () => {
    it('flags stale when the file changes on disk', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0); // seed baseline + initial text fetch
        });
        expect(latest.stale).toBe(false);

        currentEtag = 'v2'; // someone rewrote the file
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000); // next poll tick detects it
        });
        expect(latest.stale).toBe(true);
    });

    it('refresh clears the flag and refetches with a cache-busting marker', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0);
        });
        currentEtag = 'v2';
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
        });
        expect(latest.stale).toBe(true);

        await act(async () => {
            latest.refresh();
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(latest.stale).toBe(false);

        // The refetch must dodge the browser cache for the updated bytes.
        const getUrls = global.fetch.mock.calls
            .filter(([, opts]) => !opts || opts.method !== 'HEAD')
            .map(([url]) => url);
        expect(getUrls.some((u) => u.includes('v=1'))).toBe(true);
    });

    it('does not watch inline (base64) content with no disk path', async () => {
        const inlineItem = {
            filename: 'note.txt',
            content_type: 'text/plain',
            content: btoa('inline body'),
        };
        await act(async () => {
            render(<Harness item={inlineItem} />);
            await vi.advanceTimersByTimeAsync(8000);
        });
        expect(latest.stale).toBe(false);
        expect(global.fetch).not.toHaveBeenCalled();
    });
});
