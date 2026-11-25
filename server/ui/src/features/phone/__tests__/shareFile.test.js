import { afterEach, describe, expect, it, vi } from 'vitest';

import { canShareFiles, shareFile } from '../shareFile.js';

function readText(file) {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.readAsText(file);
    });
}

function stubShare({ canShare = true, share = vi.fn(async () => {}) } = {}) {
    vi.stubGlobal('navigator', { ...navigator, canShare: vi.fn(() => canShare), share });
    return share;
}

describe('shareFile', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('reports sharing as unavailable without the Web Share API', () => {
        vi.stubGlobal('navigator', { ...navigator, canShare: undefined, share: undefined });
        expect(canShareFiles()).toBe(false);
    });

    it('shares a file loaded from its container path', async () => {
        const share = stubShare();
        const fetchFile = vi.fn(async () => ({ ok: true, blob: async () => new Blob(['# Notes']) }));
        vi.stubGlobal('fetch', fetchFile);

        const shared = await shareFile({ filename: 'notes.md', content_type: 'text/markdown', path: '/home/omnideck/notes.md' });

        expect(shared).toBe(true);
        expect(fetchFile.mock.calls[0][0]).toContain('notes.md');
        const { files, title } = share.mock.calls[0][0];
        expect(title).toBe('notes.md');
        expect(files[0].name).toBe('notes.md');
        expect(files[0].type).toBe('text/markdown');
        expect(await readText(files[0])).toBe('# Notes');
    });

    it('shares inline file content', async () => {
        const share = stubShare();

        await shareFile({ filename: 'hello.txt', content_type: 'text/plain', content: btoa('hello') });

        expect(await readText(share.mock.calls[0][0].files[0])).toBe('hello');
    });

    it('resolves false when the person closes the share menu', async () => {
        stubShare({ share: vi.fn(async () => { throw new DOMException('closed', 'AbortError'); }) });
        await expect(shareFile({ filename: 'a.txt', content: btoa('a') })).resolves.toBe(false);
    });

    it('fails when the file cannot be loaded', async () => {
        stubShare();
        vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
        await expect(shareFile({ filename: 'gone.md', path: '/gone.md' })).rejects.toThrow('The file could not be loaded.');
    });

    it('fails when the browser cannot share this file type', async () => {
        stubShare({ canShare: false });
        await expect(shareFile({ filename: 'a.bin', content: btoa('a') })).rejects.toThrow('This file type can\'t be shared.');
    });
});
