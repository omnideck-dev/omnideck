import { describe, it, expect } from 'vitest';
import {
    detectComposerTrigger,
    applyComposerToken,
    findComposerTokens,
    resolveComposerItem,
    removeComposerTokens,
    composerTokenFor,
} from '../useComposerTrigger.js';
import shared from '../../../../../tests/fixtures/composer_skill_matching.json';

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

describe('findComposerTokens', () => {
    it('finds tokens at the start and after whitespace only', () => {
        expect(findComposerTokens('/a then b/c and /d', TRIGGERS).map((t) => t.ref)).toEqual(['a', 'd']);
    });

    it('treats a path as a single token', () => {
        expect(findComposerTokens('look at /tmp/x.txt', TRIGGERS)).toEqual([
            { trigger: '/', ref: 'tmp/x.txt', start: 8, end: 18 },
        ]);
    });

    it('ignores a bare trigger with no name', () => {
        expect(findComposerTokens('a / b', TRIGGERS)).toEqual([]);
    });
});

describe('resolveComposerItem', () => {
    // The server's resolver runs the same cases, keeping both sides in step.
    it.each(shared.cases)('resolves $ref ($why)', ({ ref, expect: expected }) => {
        expect(resolveComposerItem(ref, shared.skills)?.id ?? null).toBe(expected);
    });
});

describe('composerTokenFor', () => {
    it('inserts a token that resolves back to the chosen skill', () => {
        for (const item of shared.skills) {
            expect(resolveComposerItem(composerTokenFor(item, shared.skills), shared.skills).id).toBe(item.id);
        }
    });

    it('prefers the name, then the slug, then the id', () => {
        const byId = (id) => shared.skills.find((s) => s.id === id);
        expect(composerTokenFor(byId('skill_review'), shared.skills)).toBe('review-code');
        expect(composerTokenFor(byId('4dffecbf8559'), shared.skills)).toBe('joke-teller');
        expect(composerTokenFor(byId('skill_clash_1'), shared.skills)).toBe('skill_clash_1');
    });
});

describe('removeComposerTokens', () => {
    it('removes each token with one adjoining space', () => {
        const text = '/a do this /a then that';
        const tokens = findComposerTokens(text, TRIGGERS);
        expect(removeComposerTokens(text, tokens)).toBe('do this then that');
    });

    it('takes the preceding space for a token at the end', () => {
        const text = 'do this /a';
        expect(removeComposerTokens(text, findComposerTokens(text, TRIGGERS))).toBe('do this');
    });
});
