import { describe, expect, it, vi } from 'vitest';
import { mergeTerminalEvent, formatElapsed, formatTokens, formatAgentName } from '../agentUtils.js';

describe('formatTokens', () => {
    it('returns null for null/undefined input', () => {
        expect(formatTokens(null)).toBeNull();
        expect(formatTokens(undefined)).toBeNull();
    });

    it('returns the number as a string below 1,000', () => {
        expect(formatTokens(0)).toBe('0');
        expect(formatTokens(42)).toBe('42');
        expect(formatTokens(999)).toBe('999');
    });

    it('uses Math.round (no decimals) for the k range', () => {
        expect(formatTokens(1000)).toBe('1k');
        expect(formatTokens(12847)).toBe('13k');
        expect(formatTokens(200000)).toBe('200k');
        expect(formatTokens(4200)).toBe('4k');
        expect(formatTokens(32000)).toBe('32k');
        expect(formatTokens(20000)).toBe('20k');
        expect(formatTokens(12000)).toBe('12k');
        expect(formatTokens(8000)).toBe('8k');
    });

    it('uses one decimal for the M range', () => {
        expect(formatTokens(1_000_000)).toBe('1.0M');
        expect(formatTokens(2_500_000)).toBe('2.5M');
    });
});

describe('formatAgentName', () => {
    it('returns "Agent" for falsy input', () => {
        expect(formatAgentName(null)).toBe('Agent');
        expect(formatAgentName('')).toBe('Agent');
        expect(formatAgentName(undefined)).toBe('Agent');
    });

    it('replaces underscores with spaces and title-cases each word', () => {
        expect(formatAgentName('coder')).toBe('Coder');
        expect(formatAgentName('sub_agent')).toBe('Sub Agent');
        expect(formatAgentName('data_analyst_v2')).toBe('Data Analyst V2');
    });
});

describe('formatElapsed', () => {
    it('returns null when startedAt is falsy', () => {
        expect(formatElapsed(null, null)).toBeNull();
        expect(formatElapsed(0, null)).toBeNull();
    });

    it('formats seconds only when under 60s', () => {
        expect(formatElapsed(1000, 1500)).toBe('0s');
        expect(formatElapsed(1000, 11000)).toBe('10s');
        expect(formatElapsed(1000, 59000)).toBe('58s');
    });

    it('formats minutes and seconds when 60s or more', () => {
        expect(formatElapsed(1000, 61000)).toBe('1m 0s');
        expect(formatElapsed(1000, 72000)).toBe('1m 11s');
        expect(formatElapsed(1000, 3725000)).toBe('62m 4s');
    });

    it('uses Date.now() when completedAt is not provided', () => {
        // Pin the clock so the elapsed calculation can't straddle a second boundary.
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-01-01T00:00:05Z'));
        const startedAt = new Date('2026-01-01T00:00:00Z').getTime();
        expect(formatElapsed(startedAt)).toBe('5s');
        vi.useRealTimers();
    });
});

describe('mergeTerminalEvent', () => {
    const baseEvent = { cmd_id: 'cmd-1', status: 'done', stdout: 'hello', stderr: null };

    it('appends a new event when the cmd_id is not present', () => {
        const result = mergeTerminalEvent([], baseEvent);
        expect(result).toHaveLength(1);
        expect(result[0]).toEqual(baseEvent);
    });

    it('replaces an existing event when status is not streaming', () => {
        const existing = [{ ...baseEvent, stdout: 'old' }];
        const update = { cmd_id: 'cmd-1', status: 'done', stdout: 'new', stderr: null };
        const result = mergeTerminalEvent(existing, update);
        expect(result).toHaveLength(1);
        expect(result[0].stdout).toBe('new');
    });

    it('concatenates stdout/stderr when status is streaming', () => {
        const existing = [{ cmd_id: 'cmd-1', status: 'streaming', stdout: 'hello ', stderr: null }];
        const update = { cmd_id: 'cmd-1', status: 'streaming', stdout: 'world', stderr: 'err' };
        const result = mergeTerminalEvent(existing, update);
        expect(result).toHaveLength(1);
        expect(result[0].stdout).toBe('hello world');
        expect(result[0].stderr).toBe('err');
    });

    it('trims to maxLines from the end', () => {
        // Use a unique cmd_id so the event is appended, not replaced.
        const lines = Array.from({ length: 60 }, (_, i) => ({ cmd_id: `cmd-${i}`, status: 'done', stdout: '', stderr: null }));
        const newEvent = { cmd_id: 'cmd-new', status: 'done', stdout: 'hello', stderr: null };
        const result = mergeTerminalEvent(lines, newEvent, 50);
        expect(result).toHaveLength(50);
        // 60 existing + 1 appended = 61, slice(-50) keeps the last 50.
        expect(result[49].cmd_id).toBe('cmd-new');
    });
});
