import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    downloadProfileBundle,
    downloadSkillBundle,
    importBundleFile,
    importSummaryText,
} from '../bundles.js';

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

// A minimal File-like stand-in whose text() resolves to the given string.
function fileWith(text, { throws = false } = {}) {
    return { text: () => (throws ? Promise.reject(new Error('io')) : Promise.resolve(text)) };
}

describe('importSummaryText', () => {
    it('summarizes profiles and skills', () => {
        expect(importSummaryText({ profiles: [1, 2], skills: [1] })).toBe('Imported 2 agents and 1 skill.');
    });
    it('handles a single profile only', () => {
        expect(importSummaryText({ profiles: [1] })).toBe('Imported 1 agent.');
    });
    it('handles skills only', () => {
        expect(importSummaryText({ skills: [1, 2] })).toBe('Imported 2 skills.');
    });
    it('handles nothing', () => {
        expect(importSummaryText({})).toBe('Nothing to import.');
    });
});

describe('download helpers', () => {
    function captureAnchor() {
        const anchor = { href: '', rel: '', click: vi.fn() };
        vi.spyOn(document, 'createElement').mockReturnValue(anchor);
        return anchor;
    }

    it('builds the profile export URL with options and clicks a download', () => {
        const anchor = captureAnchor();
        downloadProfileBundle('abc', { includeSkills: true, includeModel: false });
        expect(anchor.href).toContain('/api/profiles/abc/export?');
        expect(anchor.href).toContain('include_skills=true');
        expect(anchor.href).toContain('include_model=false');
        expect(anchor.click).toHaveBeenCalled();
    });

    it('defaults profile export options', () => {
        const anchor = captureAnchor();
        downloadProfileBundle('abc');
        expect(anchor.href).toContain('include_skills=false');
        expect(anchor.href).toContain('include_model=true');
    });

    it('builds the skill export URL', () => {
        const anchor = captureAnchor();
        downloadSkillBundle('xyz');
        expect(anchor.href).toContain('/api/skills/xyz/export');
        expect(anchor.click).toHaveBeenCalled();
    });
});

describe('importBundleFile', () => {
    it('rejects a file that will not read', async () => {
        const result = await importBundleFile(fileWith('', { throws: true }));
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/read/i);
    });

    it('rejects a file that is not JSON', async () => {
        const result = await importBundleFile(fileWith('not json {'));
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/not a valid export/i);
    });

    it('posts parsed JSON to /api/import and returns data on success', async () => {
        const data = { profiles: [{ id: 'x' }], skills: [] };
        global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
        const result = await importBundleFile(fileWith('{"kind":"omnideck.bundle","skills":[]}'));
        expect(result.ok).toBe(true);
        expect(result.data).toEqual(data);
        const [url, init] = global.fetch.mock.calls[0];
        expect(url).toBe('/api/import');
        expect(init.method).toBe('POST');
        expect(JSON.parse(init.body)).toEqual({ kind: 'omnideck.bundle', skills: [] });
    });

    it('surfaces a server error message', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Not a valid omnideck bundle' }) });
        const result = await importBundleFile(fileWith('{"kind":"x"}'));
        expect(result.ok).toBe(false);
        expect(result.error).toBe('Not a valid omnideck bundle');
    });
});
