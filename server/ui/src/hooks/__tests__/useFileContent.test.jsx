import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useFileContent from '../useFileContent.js';
import { _reset as resetFileWatch } from '../../utils/fileWatchStore.js';

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
    delete window.omnideckHost;
    vi.useRealTimers();
    vi.restoreAllMocks();
    resetFileWatch();
    latest = undefined;
});

const textItem = {
    filename: 'analysis.md',
    content_type: 'text/markdown',
    path: '/home/user/analysis.md',
};

describe('useFileContent disk-change watcher', () => {
    it('downloads a disk-backed artifact through its native-streamable path', async () => {
        window.omnideckHost = Object.freeze({});
        const anchor = document.createElement('a');
        anchor.click = vi.fn();
        vi.spyOn(document, 'createElement').mockReturnValue(anchor);
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0);
        });

        act(() => latest.handleDownload());

        expect(anchor.href).toContain(textItem.path);
        expect(anchor.download).toBe(textItem.filename);
        expect(anchor.click).toHaveBeenCalledTimes(1);
    });

    it('auto-refreshes content when the file changes on disk', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0); // seed baseline + initial fetch
        });
        expect(latest.text).toBe('body@v1');
        expect(latest.stale).toBe(false);

        currentEtag = 'v2'; // someone rewrote the file
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000); // poll tick detects change → auto-refresh
            await vi.advanceTimersByTimeAsync(0);    // let refetch promise resolve
        });
        // stale is immediately cleared by the auto-refresh
        expect(latest.stale).toBe(false);
        // content is updated without any manual refresh call
        expect(latest.text).toBe('body@v2');

        // Probes must bypass the browser cache or stale bytes go unseen.
        const headOpts = global.fetch.mock.calls
            .filter(([, opts]) => opts && opts.method === 'HEAD')
            .map(([, opts]) => opts);
        expect(headOpts.length).toBeGreaterThan(0);
        expect(headOpts.every((o) => o.cache === 'no-store')).toBe(true);
    });

    it('auto-refresh fetches with a cache-busting version marker', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0);
        });

        currentEtag = 'v2';
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(latest.stale).toBe(false);

        // The auto-refresh must use a version bump to dodge the browser cache.
        const getUrls = global.fetch.mock.calls
            .filter(([, opts]) => !opts || opts.method !== 'HEAD')
            .map(([url]) => url);
        expect(getUrls.some((u) => u.includes('v=1'))).toBe(true);
    });

    it('auto-refresh propagates to all previews of the same file', async () => {
        // Mirrors multiple mounted views of the same artifact.
        function TwoViews({ item }) {
            const a = useFileContent(item);
            const b = useFileContent(item);
            latest = { a, b };
            return null;
        }
        await act(async () => {
            render(<TwoViews item={textItem} />);
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(latest.a.text).toBe('body@v1');
        expect(latest.b.text).toBe('body@v1');

        currentEtag = 'v2';
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
            await vi.advanceTimersByTimeAsync(0);
        });
        // Both views update without any explicit refresh call.
        expect(latest.a.stale).toBe(false);
        expect(latest.b.stale).toBe(false);
        expect(latest.a.text).toBe('body@v2');
        expect(latest.b.text).toBe('body@v2');
    });

    it('tracks the edit buffer and saves it back with a PUT', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0); // seed baseline + load text
        });
        expect(latest.text).toBe('body@v1');
        expect(latest.draft).toBe('body@v1');
        expect(latest.isDirty).toBe(false);
        expect(latest.canSave).toBe(true);

        // Editing the buffer flips the dirty flag without touching disk.
        act(() => latest.setDraft('edited body'));
        expect(latest.isDirty).toBe(true);

        // The rewrite lands on disk, so a save reload should read it back.
        currentEtag = 'v2';
        global.fetch.mockImplementation((url, opts) => {
            if (opts && opts.method === 'PUT') return Promise.resolve({ ok: true });
            const isHead = opts && opts.method === 'HEAD';
            return Promise.resolve(
                makeResponse({ etag: currentEtag, body: isHead ? '' : 'edited body' }),
            );
        });

        await act(async () => {
            await latest.save();
            await vi.advanceTimersByTimeAsync(0); // let the reload settle
        });

        const putCalls = global.fetch.mock.calls.filter(([, o]) => o && o.method === 'PUT');
        expect(putCalls.length).toBe(1);
        expect(putCalls[0][0]).toBe(textItem.path);
        expect(putCalls[0][1].body).toBe('edited body');
        expect(latest.text).toBe('edited body');
        expect(latest.isDirty).toBe(false);
    });

    it('does not auto-refresh over an unsaved draft, and resumes once it is no longer dirty', async () => {
        await act(async () => {
            render(<Harness item={textItem} />);
            await vi.advanceTimersByTimeAsync(0); // seed baseline + load text
        });
        act(() => latest.setDraft('edited body'));
        expect(latest.isDirty).toBe(true);

        // The file changes on disk while the draft has unsaved edits.
        currentEtag = 'v2';
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000); // poll tick marks it stale
            await vi.advanceTimersByTimeAsync(0);
        });
        // Auto-refresh must not clobber the in-progress edit.
        expect(latest.stale).toBe(true);
        expect(latest.text).toBe('body@v1');
        expect(latest.draft).toBe('edited body');

        // Discarding the edit clears isDirty, which lets the pending refresh through.
        act(() => latest.setDraft('body@v1'));
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(latest.stale).toBe(false);
        expect(latest.text).toBe('body@v2');
    });

    it('does not offer save for inline (base64) content with no path', async () => {
        const inlineItem = {
            filename: 'note.txt',
            content_type: 'text/plain',
            content: btoa('inline body'),
        };
        await act(async () => {
            render(<Harness item={inlineItem} />);
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(latest.canSave).toBe(false);
        expect(latest.draft).toBe('inline body');
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
