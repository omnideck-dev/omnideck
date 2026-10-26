import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { watchStylesheet } from '../customCssWatch.js';
import * as fileWatch from '../fileWatchStore.js';

const headResponse = (etag) => ({ ok: true, headers: new Headers(etag ? { ETag: etag } : {}) });

// jsdom never fetches stylesheets, so tests fire the load/error events themselves.
const links = () => [...document.head.querySelectorAll('link')];
const hrefs = () => links().map((l) => l.getAttribute('href'));

describe('watchStylesheet', () => {
    let link;
    let stop;

    beforeEach(() => {
        vi.useFakeTimers();
        fileWatch._reset();
        document.head.innerHTML = '';
        link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/custom.css';
        document.head.appendChild(link);
    });

    afterEach(() => {
        if (stop) stop();
        stop = null;
        vi.useRealTimers();
        vi.unstubAllGlobals();
        document.head.innerHTML = '';
    });

    it('loads the edited file in a second link and keeps the live one until it loads', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(headResponse('"a"')) // baseline
            .mockResolvedValueOnce(headResponse('"a"')) // unchanged
            .mockResolvedValueOnce(headResponse('"b"')); // edited
        vi.stubGlobal('fetch', fetchMock);

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css']);

        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=1']);
        expect(link.isConnected).toBe(true); // old styles stay live while the new ones load
        expect(fetchMock).toHaveBeenCalledWith('/custom.css', { method: 'HEAD', cache: 'no-store' });
    });

    it('removes the old link only after the new one has loaded', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        const next = links()[1];

        next.dispatchEvent(new Event('load'));

        expect(hrefs()).toEqual(['/custom.css?v=1']);
        expect(link.isConnected).toBe(false);
    });

    it('places the replacement right after the live link so the cascade order is unchanged', async () => {
        const later = document.createElement('link');
        later.rel = 'stylesheet';
        later.href = '/assets/lazy.css';
        document.head.appendChild(later);
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        links()[1].dispatchEvent(new Event('load'));

        expect(hrefs()).toEqual(['/custom.css?v=1', '/assets/lazy.css']);
    });

    it('keeps the working stylesheet when the new one fails to load', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        links()[1].dispatchEvent(new Event('error'));

        expect(hrefs()).toEqual(['/custom.css']);
        expect(link.isConnected).toBe(true);
    });

    it('drops an unfinished replacement when a newer edit arrives', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"'))
            .mockResolvedValueOnce(headResponse('"c"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(8000);

        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=2']);
    });

    it('records the change in the shared file-watch store and clears the stale flag', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);

        expect(fileWatch.getSnapshot('/custom.css')).toEqual({ version: 1, stale: false });
    });

    it('refreshes once per edit, not on every poll after it', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"'))
            .mockResolvedValue(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(12000);

        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=1']);
    });

    it('does not poll after being stopped, and discards an unfinished replacement', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValue(headResponse('"b"'));
        vi.stubGlobal('fetch', fetchMock);

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=1']);

        stop();
        stop = null;
        expect(hrefs()).toEqual(['/custom.css']);
        const callsAfterStop = fetchMock.mock.calls.length;
        await vi.advanceTimersByTimeAsync(20000);
        expect(fetchMock.mock.calls.length).toBe(callsAfterStop);
    });

    it('starts watching even if the startup probe fails', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockRejectedValueOnce(new Error('app restarting')) // startup probe fails
            .mockResolvedValueOnce(headResponse('"a"')) // first tick records the baseline
            .mockResolvedValueOnce(headResponse('"b"'))); // edited

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css']); // baseline only, nothing to refresh yet

        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=1']);
    });

    it('also recovers when the startup probe gets an error status', async () => {
        vi.stubGlobal('fetch', vi.fn()
            .mockResolvedValueOnce({ ok: false, headers: new Headers() })
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockResolvedValueOnce(headResponse('"b"')));

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(8000);

        expect(hrefs()).toEqual(['/custom.css', '/custom.css?v=1']);
    });

    it('ignores network errors and keeps the current stylesheet', async () => {
        const fetchMock = vi.fn()
            .mockResolvedValueOnce(headResponse('"a"'))
            .mockRejectedValueOnce(new Error('offline'));
        vi.stubGlobal('fetch', fetchMock);

        stop = watchStylesheet(link, '/custom.css');
        await vi.advanceTimersByTimeAsync(4000);
        expect(hrefs()).toEqual(['/custom.css']);
    });
});
