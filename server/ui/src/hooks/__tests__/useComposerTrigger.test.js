import { describe, it, expect } from 'vitest';
import { detectComposerTrigger, applyComposerToken } from '../useComposerTrigger.js';

const TRIGGERS = ['/'];

describe('detectComposerTrigger', () => {
    it('detects a / trigger at the start of the message', () => {
        expect(detectComposerTrigger('/rev', 4, TRIGGERS)).toEqual({ trigger: '/', triggerIndex: 0, query: 'rev' });
    });

    it('ignores characters that are not registered triggers', () => {
        expect(detectComposerTrigger('hi @co', 6, TRIGGERS)).toBeNull();
    });

    it('detects any registered trigger character', () => {
        expect(detectComposerTrigger('hi @co #t', 6, ['/', '@', '#'])).toEqual({ trigger: '@', triggerIndex: 3, query: 'co' });
        expect(detectComposerTrigger('hi @co #t', 9, ['/', '@', '#'])).toEqual({ trigger: '#', triggerIndex: 7, query: 't' });
    });

    it('does not trigger mid-word for any registered character', () => {
        expect(detectComposerTrigger('user@host', 9, ['/', '@'])).toBeNull();
    });

    it('does not trigger on a mid-word slash', () => {
        expect(detectComposerTrigger('a/b', 3, TRIGGERS)).toBeNull();
    });

    it('closes once whitespace is typed after the query', () => {
        expect(detectComposerTrigger('/rev ', 5, TRIGGERS)).toBeNull();
    });

    it('closes when the cursor moves outside the token span', () => {
        // Cursor is back at the very start, before the trigger character.
        expect(detectComposerTrigger('/review-code', 0, TRIGGERS)).toBeNull();
    });

    it('returns an empty query right after the bare trigger character', () => {
        expect(detectComposerTrigger('/', 1, TRIGGERS)).toEqual({ trigger: '/', triggerIndex: 0, query: '' });
    });

    it('detects a trigger mid-message when preceded by whitespace', () => {
        const text = 'do this /sum';
        expect(detectComposerTrigger(text, text.length, TRIGGERS)).toEqual({ trigger: '/', triggerIndex: 8, query: 'sum' });
    });
});

describe('applyComposerToken', () => {
    it('replaces the trigger token and adds a trailing space', () => {
        const result = applyComposerToken('/rev', { triggerIndex: 0 }, '/review-code');
        expect(result.text).toBe('/review-code ');
        expect(result.cursorIndex).toBe('/review-code '.length);
    });

    it('preserves surrounding text on either side of the token', () => {
        const result = applyComposerToken('hi /rev do it', { triggerIndex: 3 }, '/review-code');
        expect(result.text).toBe('hi /review-code  do it');
        expect(result.cursorIndex).toBe('hi /review-code '.length);
    });

    it('replaces the whole query run even if the cursor was mid-token', () => {
        const result = applyComposerToken('/review-code', { triggerIndex: 0 }, '/review-code');
        expect(result.text).toBe('/review-code ');
    });
});
