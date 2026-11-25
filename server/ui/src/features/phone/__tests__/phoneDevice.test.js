import { afterEach, describe, expect, it, vi } from 'vitest';

import { isPhoneDevice } from '../phoneDevice.js';

function screenOf(width, height, { touch = true } = {}) {
    vi.stubGlobal('screen', { width, height });
    vi.stubGlobal('matchMedia', vi.fn((query) => ({ matches: query === '(pointer: coarse)' && touch })));
}

describe('isPhoneDevice', () => {
    afterEach(() => vi.unstubAllGlobals());

    it('is true for a phone held upright', () => {
        screenOf(390, 844);
        expect(isPhoneDevice()).toBe(true);
    });

    it('is true for a phone held sideways', () => {
        screenOf(932, 430);
        expect(isPhoneDevice()).toBe(true);
    });

    it('is false for a regular iPad held sideways, whatever space the browser toolbars take', () => {
        screenOf(1180, 820);
        vi.stubGlobal('innerHeight', 750);
        expect(isPhoneDevice()).toBe(false);
    });

    it('is false for a tablet in either direction', () => {
        screenOf(1024, 1366);
        expect(isPhoneDevice()).toBe(false);
        screenOf(1366, 1024);
        expect(isPhoneDevice()).toBe(false);
    });

    it('is false on a narrow window with a mouse', () => {
        screenOf(600, 800, { touch: false });
        expect(isPhoneDevice()).toBe(false);
    });

    it('is false when the browser has no media queries', () => {
        vi.stubGlobal('matchMedia', undefined);
        expect(isPhoneDevice()).toBe(false);
    });
});
