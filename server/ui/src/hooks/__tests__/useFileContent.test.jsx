import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useFileContent from '../useFileContent.js';
import { _reset as resetFileWatch } from '../../utils/fileWatchStore.js';

// Captures the hook's latest return value so assertions can read it between acts.
let latest;
function Harness({ item, visible }) {
    latest = useFileContent(item, { visible });
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
const headCalls = () => global.fetch.mock.calls.filter(([, opts]) => opts?.method === 'HEAD');

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

        // The probe must bypass the browser cache, or it reads a stale validator.
        const headOpts = global.fetch.mock.calls
            .filter(([, opts]) => opts && opts.method === 'HEAD')
            .map(([, opts]) => opts);
        expect(headOpts.length).toBeGreaterThan(0);
        expect(headOpts.every((o) => o.cache === 'no-store')).toBe(true);
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

    it('shares stale and refresh across previews of the same file', async () => {
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
        expect(headCalls()).toHaveLength(1);
        currentEtag = 'v2';
        await act(async () => {
            await vi.advanceTimersByTimeAsync(4000);
        });
        expect(latest.a.stale).toBe(true);
        expect(latest.b.stale).toBe(true);
        expect(headCalls()).toHaveLength(2);

        // Refreshing through one view must clear the other.
        await act(async () => {
            latest.a.refresh();
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(latest.a.stale).toBe(false);
        expect(latest.b.stale).toBe(false);
        expect(headCalls()).toHaveLength(3);
    });

    it('pauses hidden previews and detects changes on return without losing edits', async () => {
        const view = render(<Harness item={textItem} visible={false} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(headCalls()).toHaveLength(1); // one baseline; no hidden polling

        view.rerender(<Harness item={textItem} visible />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(headCalls()).toHaveLength(2);
        act(() => latest.setDraft('unsaved edits'));

        view.rerender(<Harness item={textItem} visible={false} />);
        currentEtag = 'v2';
        await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
        expect(headCalls()).toHaveLength(2);

        view.rerender(<Harness item={textItem} visible />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(headCalls()).toHaveLength(3);
        expect(latest.stale).toBe(true);
        expect(latest.draft).toBe('unsaved edits');
    });

    it('detects changes before a restored hidden preview is first activated', async () => {
        const view = render(<Harness item={textItem} visible={false} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(latest.text).toBe('body@v1');
        expect(headCalls()).toHaveLength(1);
        currentEtag = 'v2';
        await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
        expect(headCalls()).toHaveLength(1);

        view.rerender(<Harness item={textItem} visible />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(headCalls()).toHaveLength(2);
        expect(latest.stale).toBe(true);
        expect(latest.text).toBe('body@v1');
    });

    it('keeps the shared watcher running until its last visible preview hides', async () => {
        function TwoViews({ first, second }) {
            useFileContent(textItem, { visible: first });
            useFileContent(textItem, { visible: second });
            return null;
        }
        const view = render(<TwoViews first second />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        expect(headCalls()).toHaveLength(1);

        view.rerender(<TwoViews first={false} second />);
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(headCalls()).toHaveLength(2);
        view.rerender(<TwoViews first={false} second={false} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(headCalls()).toHaveLength(2);
    });

    it('pauses with the whole document and catches up when it becomes visible', async () => {
        let hidden = false;
        vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
        render(<Harness item={textItem} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        hidden = true;
        document.dispatchEvent(new Event('visibilitychange'));
        currentEtag = 'v2';
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(headCalls()).toHaveLength(1);

        hidden = false;
        await act(async () => {
            document.dispatchEvent(new Event('visibilitychange'));
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(headCalls()).toHaveLength(2);
        expect(latest.stale).toBe(true);
    });

    it('serializes slow probes and ignores an old response after refresh', async () => {
        render(<Harness item={textItem} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        let finishProbe;
        global.fetch.mockImplementationOnce(() => new Promise((resolve) => { finishProbe = resolve; }));
        await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
        expect(headCalls()).toHaveLength(2);

        currentEtag = 'v3';
        await act(async () => {
            latest.refresh();
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(headCalls()[1][1].signal.aborted).toBe(true);
        expect(headCalls()).toHaveLength(2);
        await act(async () => {
            finishProbe(makeResponse({ etag: 'v2' }));
            await vi.advanceTimersByTimeAsync(0);
        });
        expect(headCalls()).toHaveLength(3);
        expect(latest.stale).toBe(false);
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(latest.stale).toBe(false);
    });

    it('retries a failed initial baseline instead of disabling watching', async () => {
        const originalFetch = global.fetch.getMockImplementation();
        let firstProbe = true;
        global.fetch.mockImplementation((url, opts) => {
            if (opts?.method === 'HEAD' && firstProbe) {
                firstProbe = false;
                return Promise.reject(new Error('offline'));
            }
            return originalFetch(url, opts);
        });
        render(<Harness item={textItem} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(headCalls()).toHaveLength(2);
        currentEtag = 'v2';
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(latest.stale).toBe(true);
    });

    it('aborts an unfinished probe when the final preview closes', async () => {
        const view = render(<Harness item={textItem} />);
        await act(async () => { await vi.advanceTimersByTimeAsync(0); });
        let finishProbe;
        global.fetch.mockImplementationOnce(() => new Promise((resolve) => { finishProbe = resolve; }));
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        view.unmount();
        expect(headCalls()[1][1].signal.aborted).toBe(true);
        await act(async () => {
            finishProbe(makeResponse({ etag: 'v2' }));
            await vi.advanceTimersByTimeAsync(12000);
        });
        expect(headCalls()).toHaveLength(2);
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
