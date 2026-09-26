import { describe, it, expect } from 'vitest';
import { detectComposerTrigger, applyComposerToken } from '../useComposerTrigger.js';

describe('detectComposerTrigger', () => {
    it('detects a / trigger at the start of the message', () => {
        expect(detectComposerTrigger('/rev', 4)).toEqual({ kind: 'skill', triggerIndex: 0, query: 'rev' });
    });

    it('detects an @ trigger immediately after whitespace', () => {
        expect(detectComposerTrigger('hi @co', 6)).toEqual({ kind: 'agent', triggerIndex: 3, query: 'co' });
    });

    it('does not trigger on a mid-word slash', () => {
        expect(detectComposerTrigger('a/b', 3)).toBeNull();
    });

    it('does not trigger on a mid-word @', () => {
        expect(detectComposerTrigger('user@host', 9)).toBeNull();
    });

    it('closes once whitespace is typed after the query', () => {
        expect(detectComposerTrigger('/rev ', 5)).toBeNull();
    });

    it('closes when the cursor moves outside the token span', () => {
        // Cursor is back at the very start, before the trigger character.
        expect(detectComposerTrigger('/review-code', 0)).toBeNull();
    });

    it('returns an empty query right after the bare trigger character', () => {
        expect(detectComposerTrigger('/', 1)).toEqual({ kind: 'skill', triggerIndex: 0, query: '' });
    });

    it('detects a trigger mid-message when preceded by whitespace', () => {
        const text = 'do this @agent-y';
        expect(detectComposerTrigger(text, text.length)).toEqual({
            kind: 'agent',
            triggerIndex: 8,
            query: 'agent-y',
        });
    });
});

describe('applyComposerToken', () => {
    it('replaces the trigger token and adds a trailing space', () => {
        const result = applyComposerToken('/rev', { triggerIndex: 0 }, '/review-code');
        expect(result.text).toBe('/review-code ');
        expect(result.cursorIndex).toBe('/review-code '.length);
    });

    it('preserves surrounding text on either side of the token', () => {
        const result = applyComposerToken('hi @co do it', { triggerIndex: 3 }, '@coder');
        expect(result.text).toBe('hi @coder  do it');
        expect(result.cursorIndex).toBe('hi @coder '.length);
    });

    it('replaces the whole query run even if the cursor was mid-token', () => {
        const result = applyComposerToken('/review-code', { triggerIndex: 0 }, '/review-code');
        expect(result.text).toBe('/review-code ');
    });
});
