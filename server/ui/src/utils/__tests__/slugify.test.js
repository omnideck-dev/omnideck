import { describe, expect, it } from 'vitest';
import { slugify } from '../slugify.js';

describe('slugify', () => {
    it('lowercases and hyphenates a simple multi-word name', () => {
        expect(slugify('Joke teller')).toBe('joke-teller');
    });

    it('collapses runs of separators and punctuation into one hyphen', () => {
        expect(slugify('joke   TELLER!!')).toBe('joke-teller');
    });

    it('trims leading and trailing hyphens', () => {
        expect(slugify('  Joke teller  ')).toBe('joke-teller');
        expect(slugify('!!Joke teller!!')).toBe('joke-teller');
    });

    it('leaves a single-word name that needs no changes untouched but lowercased', () => {
        expect(slugify('Coder')).toBe('coder');
    });

    it('returns an empty string for input with no alphanumeric characters', () => {
        expect(slugify('!!!')).toBe('');
    });
});
