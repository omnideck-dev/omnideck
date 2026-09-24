import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { clearChatDraft, loadChatDraft, saveChatDraft } from '../chatDraftStorage.js';

describe('chatDraftStorage', () => {
    beforeEach(() => {
        localStorage.clear();
    });

    it('returns an empty string when nothing is saved', () => {
        expect(loadChatDraft('convo-1')).toBe('');
    });

    it('saves and loads a draft by conversation id', () => {
        saveChatDraft('convo-1', 'hello there');
        expect(loadChatDraft('convo-1')).toBe('hello there');
    });

    it('clears the entry once the text is empty', () => {
        saveChatDraft('convo-1', 'hello there');
        saveChatDraft('convo-1', '');
        expect(localStorage.getItem('omnideck_chat_draft_v1:convo-1')).toBeNull();
    });

    it('clearChatDraft removes a persisted draft', () => {
        saveChatDraft('convo-1', 'hello there');
        clearChatDraft('convo-1');
        expect(loadChatDraft('convo-1')).toBe('');
    });

    it('no-ops without a conversation id', () => {
        saveChatDraft(undefined, 'orphaned');
        expect(loadChatDraft(undefined)).toBe('');
    });

    // Accessing `localStorage` itself (not just its methods) can throw — e.g.
    // Safari private mode raises SecurityError on the getter. Both the load
    // and save paths must swallow that rather than let it escape.
    describe('with a throwing storage getter', () => {
        let descriptor;

        beforeEach(() => {
            descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
            Object.defineProperty(globalThis, 'localStorage', {
                configurable: true,
                get() {
                    throw new DOMException('Storage access blocked', 'SecurityError');
                },
            });
        });

        afterEach(() => {
            Object.defineProperty(globalThis, 'localStorage', descriptor);
        });

        it('loadChatDraft falls back to an empty string', () => {
            expect(() => loadChatDraft('convo-1')).not.toThrow();
            expect(loadChatDraft('convo-1')).toBe('');
        });

        it('saveChatDraft is a silent no-op', () => {
            expect(() => saveChatDraft('convo-1', 'text')).not.toThrow();
        });

        it('clearChatDraft is a silent no-op', () => {
            expect(() => clearChatDraft('convo-1')).not.toThrow();
        });
    });
});
