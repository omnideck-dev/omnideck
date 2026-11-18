import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
    createThemeStylesheet,
    installThemeStylesheet,
    requestThemeRefresh,
    resetInstalledThemeStylesheet,
} from '../themeStylesheet.js';

const hrefs = () => [...document.head.querySelectorAll('link[rel="stylesheet"]')]
    .map((link) => link.getAttribute('href'));

/** The most recently added stylesheet link, i.e. the replacement still loading. */
const latest = () => [...document.head.querySelectorAll('link[rel="stylesheet"]')].at(-1);

const settle = () => vi.advanceTimersByTimeAsync(0);

/** jsdom never loads stylesheets, so tests report the outcome themselves. */
const finishLoad = async (outcome) => {
    latest().dispatchEvent(new Event(outcome));
    await settle();
};

describe('createThemeStylesheet', () => {
    let link;
    let controller;

    const start = (fetchVersion) => {
        controller = createThemeStylesheet({ link, fetchVersion });
        return controller;
    };

    beforeEach(() => {
        vi.useFakeTimers();
        document.head.innerHTML = '';
        link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/theme.css';
        document.head.appendChild(link);
    });

    afterEach(() => {
        controller?.dispose();
        controller = null;
        vi.useRealTimers();
        document.head.innerHTML = '';
    });

    it('loads the wanted version next to the live link and drops the old one only after it loads', async () => {
        start(vi.fn().mockResolvedValue('v1'));

        controller.refresh();
        await settle();
        // Both are present while the replacement downloads, so the live styles never disappear.
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v1']);

        await finishLoad('load');
        expect(hrefs()).toEqual(['/theme.css?v=v1']);
    });

    it('does nothing when the wanted version is already applied', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v1');
        start(fetchVersion);
        controller.refresh();
        await settle();
        await finishLoad('load');

        controller.refresh();
        await settle();

        expect(fetchVersion).toHaveBeenCalledTimes(2);
        expect(hrefs()).toEqual(['/theme.css?v=v1']);
    });

    it('swaps again when the theme changes', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v1');
        start(fetchVersion);
        controller.refresh();
        await settle();
        await finishLoad('load');

        fetchVersion.mockResolvedValue('v2');
        controller.refresh();
        await settle();
        expect(hrefs()).toEqual(['/theme.css?v=v1', '/theme.css?v=v2']);
        await finishLoad('load');

        expect(hrefs()).toEqual(['/theme.css?v=v2']);
    });

    it('keeps the working appearance when the replacement fails to load', async () => {
        start(vi.fn().mockResolvedValue('v2'));
        controller.refresh();
        await settle();

        await finishLoad('error');

        expect(hrefs()).toEqual(['/theme.css']);
        expect(link.isConnected).toBe(true);
    });

    it('recovers on its own after a failed load, with no further edit and no reload', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v2');
        start(fetchVersion);
        controller.refresh();
        await settle();
        await finishLoad('error');
        expect(hrefs()).toEqual(['/theme.css']);

        // The wanted version has not changed since the failure, yet the next attempt still happens.
        await vi.advanceTimersByTimeAsync(1000);
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v2']);
        await finishLoad('load');
        expect(hrefs()).toEqual(['/theme.css?v=v2']);

        // Once recovered it stops: nothing is polling in the background.
        const calls = fetchVersion.mock.calls.length;
        await vi.advanceTimersByTimeAsync(120000);
        expect(fetchVersion).toHaveBeenCalledTimes(calls);
        expect(hrefs()).toEqual(['/theme.css?v=v2']);
    });

    it('retries repeated failures on a growing delay', async () => {
        start(vi.fn().mockResolvedValue('v2'));
        controller.refresh();
        await settle();
        await finishLoad('error');

        for (const delay of [1000, 2000, 4000]) {
            await vi.advanceTimersByTimeAsync(delay - 1);
            expect(hrefs()).toEqual(['/theme.css']);
            await vi.advanceTimersByTimeAsync(1);
            expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v2']);
            await finishLoad('error');
        }
    });

    it('caps the retry delay instead of growing without bound', async () => {
        start(vi.fn().mockResolvedValue('v2'));
        controller.refresh();
        await settle();
        await finishLoad('error');
        for (const delay of [1000, 2000, 4000, 8000, 15000, 30000]) {
            await vi.advanceTimersByTimeAsync(delay);
            await finishLoad('error');
        }

        await vi.advanceTimersByTimeAsync(30000);
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v2']);
    });

    it('starts the delay over after a success', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v2');
        start(fetchVersion);
        controller.refresh();
        await settle();
        await finishLoad('error');
        await vi.advanceTimersByTimeAsync(1000);
        await finishLoad('error');
        await vi.advanceTimersByTimeAsync(2000);
        await finishLoad('load');

        fetchVersion.mockResolvedValue('v3');
        controller.refresh();
        await settle();
        await finishLoad('error');

        await vi.advanceTimersByTimeAsync(1000);
        expect(hrefs()).toEqual(['/theme.css?v=v2', '/theme.css?v=v3']);
    });

    it('retries when the version cannot be fetched and applies it once it can', async () => {
        const fetchVersion = vi.fn()
            .mockRejectedValueOnce(new Error('server restarting'))
            .mockResolvedValue('v1');
        start(fetchVersion);

        controller.refresh();
        await settle();
        expect(hrefs()).toEqual(['/theme.css']);

        await vi.advanceTimersByTimeAsync(1000);
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v1']);
        await finishLoad('load');
        expect(hrefs()).toEqual(['/theme.css?v=v1']);
    });

    it('folds requests that arrive mid-refresh into a single extra pass', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v1');
        start(fetchVersion);

        controller.refresh();
        controller.refresh();
        controller.refresh();
        await settle();
        // One pass is in flight, waiting on the stylesheet; the others are queued behind it.
        expect(fetchVersion).toHaveBeenCalledTimes(1);

        await finishLoad('load');

        // The queued requests became one extra check, which found nothing new to load.
        expect(fetchVersion).toHaveBeenCalledTimes(2);
        expect(hrefs()).toEqual(['/theme.css?v=v1']);
    });

    it('applies the newest version when the theme changes during a load', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v1');
        start(fetchVersion);
        controller.refresh();
        await settle();

        fetchVersion.mockResolvedValue('v2');
        controller.refresh();
        await settle();
        await finishLoad('load');
        expect(hrefs()).toContain('/theme.css?v=v2');
        await finishLoad('load');

        expect(hrefs()).toEqual(['/theme.css?v=v2']);
    });

    it('stops everything on dispose', async () => {
        const fetchVersion = vi.fn().mockResolvedValue('v2');
        start(fetchVersion);
        controller.refresh();
        await settle();
        await finishLoad('error');

        controller.dispose();
        await vi.advanceTimersByTimeAsync(60000);
        controller.refresh();
        await settle();

        expect(fetchVersion).toHaveBeenCalledTimes(1);
        expect(hrefs()).toEqual(['/theme.css']);
    });

    it('removes a replacement that is still loading on dispose', async () => {
        start(vi.fn().mockResolvedValue('v1'));
        controller.refresh();
        await settle();

        controller.dispose();

        expect(hrefs()).toEqual(['/theme.css']);
    });
});

describe('installThemeStylesheet', () => {
    const versionResponse = (version) => ({ ok: true, json: async () => ({ version }) });
    let hidden;

    beforeEach(() => {
        vi.useFakeTimers();
        document.head.innerHTML = '';
        hidden = false;
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(versionResponse('v1')));
    });

    afterEach(() => {
        resetInstalledThemeStylesheet();
        vi.unstubAllGlobals();
        vi.useRealTimers();
        delete document.hidden;
        document.head.innerHTML = '';
    });

    it('adds the stylesheet link and brings it up to the saved version', async () => {
        installThemeStylesheet();
        expect(hrefs()).toEqual(['/theme.css']);

        await settle();
        expect(fetch).toHaveBeenCalledWith('/api/theme', { cache: 'no-store' });
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v1']);
    });

    it('installs only once', () => {
        installThemeStylesheet();
        installThemeStylesheet();
        expect(hrefs()).toEqual(['/theme.css']);
    });

    it('re-checks on request, and a changed theme is applied', async () => {
        installThemeStylesheet();
        await settle();
        await finishLoad('load');

        fetch.mockResolvedValue(versionResponse('v2'));
        requestThemeRefresh();
        await settle();
        await finishLoad('load');

        expect(hrefs()).toEqual(['/theme.css?v=v2']);
    });

    it('ignores a request before installation', () => {
        expect(() => requestThemeRefresh()).not.toThrow();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('re-checks when a hidden tab becomes visible, but not while it stays hidden', async () => {
        installThemeStylesheet();
        await settle();
        await finishLoad('load');
        const calls = fetch.mock.calls.length;

        hidden = true;
        document.dispatchEvent(new Event('visibilitychange'));
        await settle();
        expect(fetch).toHaveBeenCalledTimes(calls);

        hidden = false;
        document.dispatchEvent(new Event('visibilitychange'));
        await settle();
        expect(fetch).toHaveBeenCalledTimes(calls + 1);
    });

    it('treats an error response as a failed check and retries it', async () => {
        fetch.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) });
        installThemeStylesheet();
        await settle();
        expect(hrefs()).toEqual(['/theme.css']);

        await vi.advanceTimersByTimeAsync(1000);
        expect(hrefs()).toEqual(['/theme.css', '/theme.css?v=v1']);
    });

    it('treats a malformed response as a failed check', async () => {
        fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ unexpected: true }) });
        installThemeStylesheet();
        await settle();

        expect(hrefs()).toEqual(['/theme.css']);
    });
});
