import { afterEach, describe, expect, it, vi } from 'vitest';
import {
    downloadProfilePack,
    downloadSkillPack,
    importPackFile,
    importSummaryText,
} from '../packs.js';

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
});

const file = new File(['{"kind":"omnideck.pack","skills":[]}'], 'coder.skill.omnideck.json');

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
        // A real <a> so appendChild/remove work; only click is stubbed (jsdom
        // would otherwise try to navigate).
        const anchor = document.createElement('a');
        anchor.click = vi.fn();
        vi.spyOn(document, 'createElement').mockReturnValue(anchor);
        return anchor;
    }

    it('builds the profile export URL with options and clicks a download', () => {
        const anchor = captureAnchor();
        downloadProfilePack('abc', { includeSkills: true, includeModel: false });
        expect(anchor.href).toContain('/api/profiles/abc/export?');
        expect(anchor.href).toContain('include_skills=true');
        expect(anchor.href).toContain('include_model=false');
        expect(anchor.click).toHaveBeenCalled();
    });

    it('defaults profile export options', () => {
        const anchor = captureAnchor();
        downloadProfilePack('abc');
        expect(anchor.href).toContain('include_skills=false');
        expect(anchor.href).toContain('include_model=true');
    });

    it('builds the skill export URL', () => {
        const anchor = captureAnchor();
        downloadSkillPack('xyz');
        expect(anchor.href).toContain('/api/skills/xyz/export');
        expect(anchor.click).toHaveBeenCalled();
    });
});

describe('importPackFile', () => {
    it('uploads the file untouched to /api/import and returns data on success', async () => {
        const data = { profiles: [{ id: 'x' }], skills: [] };
        global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => data });
        const result = await importPackFile(file);
        expect(result.ok).toBe(true);
        expect(result.data).toEqual(data);
        const [url, init] = global.fetch.mock.calls[0];
        expect(url).toBe('/api/import');
        expect(init.method).toBe('POST');
        // The file object itself is the body: no reading, no parsing, no re-encoding.
        expect(init.body).toBe(file);
    });

    it('surfaces a server error message', async () => {
        global.fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ error: 'Not a valid omnideck export file' }) });
        const result = await importPackFile(file);
        expect(result.ok).toBe(false);
        expect(result.error).toBe('Not a valid omnideck export file');
    });

    it('reports a failed request', async () => {
        global.fetch = vi.fn().mockRejectedValue(new Error('offline'));
        const result = await importPackFile(file);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/failed/i);
    });

    it('treats a 2xx with an unreadable body as a failure', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => { throw new SyntaxError('unexpected token'); },
        });
        const result = await importPackFile(file);
        expect(result.ok).toBe(false);
        expect(result.error).toMatch(/failed/i);
    });
});
