import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { label, relativeAge, buildSections } from '../conversationSections.js';

const FIXED_NOW = new Date('2026-06-01T12:00:00.000Z');
const ago = (ms) => new Date(FIXED_NOW.getTime() - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

describe('label', () => {
    it('prefers title, then first message, then a placeholder', () => {
        expect(label({ title: 'T', first_message: 'F' })).toBe('T');
        expect(label({ first_message: 'F' })).toBe('F');
        expect(label({})).toBe('(empty)');
    });
});

describe('relativeAge', () => {
    beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(FIXED_NOW); });
    afterEach(() => vi.useRealTimers());

    it('formats across minute/hour/day/week/month/year bands', () => {
        expect(relativeAge(ago(20_000))).toBe('now');
        expect(relativeAge(ago(5 * MIN))).toBe('5m');
        expect(relativeAge(ago(3 * HOUR))).toBe('3h');
        expect(relativeAge(ago(2 * DAY))).toBe('2d');
        expect(relativeAge(ago(21 * DAY))).toBe('3w');
        expect(relativeAge(ago(120 * DAY))).toBe('4mo');
        expect(relativeAge(ago(800 * DAY))).toBe('2y');
    });

    it('returns empty for missing or invalid timestamps', () => {
        expect(relativeAge('')).toBe('');
        expect(relativeAge('not-a-date')).toBe('');
    });
});

describe('buildSections', () => {
    // Date bucketing reads the wall clock, so pin it to the same instant the
    // fixtures are dated against.
    beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(FIXED_NOW); });
    afterEach(() => vi.useRealTimers());

    const folders = [{ id: 'f1', name: 'Work' }, { id: 'f2', name: 'Play' }];
    const folderById = new Map(folders.map((f) => [f.id, f]));

    const items = [
        { conversation_id: 'p', pinned: true, started_at: ago(1 * HOUR) },
        { conversation_id: 'w', folder_id: 'f1', started_at: ago(2 * HOUR) },
        { conversation_id: 't', started_at: ago(3 * HOUR) },
        { conversation_id: 'e', started_at: ago(30 * DAY) },
        { conversation_id: 'orphan', folder_id: 'gone', started_at: ago(4 * HOUR) },
    ];

    it('orders Pinned, then folders, then date buckets', () => {
        const keys = buildSections(items, folders, folderById, '').map((s) => s.key);
        expect(keys).toEqual(['pinned', 'folder:f1', 'folder:f2', 'Today', 'Earlier']);
    });

    it('places each conversation in exactly one section', () => {
        const sections = buildSections(items, folders, folderById, '');
        const byKey = Object.fromEntries(sections.map((s) => [s.key, s.items.map((i) => i.conversation_id)]));
        expect(byKey.pinned).toEqual(['p']);
        expect(byKey['folder:f1']).toEqual(['w']);
        expect(byKey['folder:f2']).toEqual([]); // empty folder still shown
        // A folder_id pointing at a deleted folder falls back to a date bucket.
        expect(byKey.Today).toEqual(expect.arrayContaining(['t', 'orphan']));
        expect(byKey.Earlier).toEqual(['e']);
    });

    it('drops empty folders while searching', () => {
        const keys = buildSections(items, folders, folderById, 'work').map((s) => s.key);
        expect(keys).not.toContain('folder:f2');
    });
});
