import { slugify } from '../utils/slugify.js';

/**
 * Pure helpers for composer shortcut tokens: detecting the trigger at the
 * cursor, splicing a picked item into the text, and finding, resolving, and
 * removing the tokens already in a message. No DOM
 * dependency — callers derive `text`/`cursorIndex` from the textarea
 * themselves, which keeps this unit-testable without rendering anything.
 */

/**
 * Find the open trigger (if any) at `cursorIndex` within `text`.
 *
 * A trigger character opens a trigger only when it's the first character of
 * the message or immediately preceded by whitespace — mid-word characters
 * (`a/b`, `user@host`) never count. The query is the run of non-whitespace
 * characters between the trigger and the cursor; the cursor must still be
 * inside that run (not past trailing whitespace) for the trigger to be open.
 *
 * @param {string} text
 * @param {number} cursorIndex
 * @param {string[]} triggers - single trigger characters, e.g. `['/']`
 * @returns {null | {trigger: string, triggerIndex: number, query: string}}
 */
export function detectComposerTrigger(text, cursorIndex, triggers) {
    if (cursorIndex <= 0 || cursorIndex > text.length) return null;

    // Scan left from the cursor for the nearest trigger character not
    // separated from the cursor by whitespace.
    let i = cursorIndex - 1;
    while (i >= 0 && !/\s/.test(text[i])) {
        i -= 1;
    }
    const triggerIndex = i + 1;
    // The run must actually reach the trigger character strictly left of the
    // cursor — a cursor sitting right after whitespace (nothing non-blank
    // between it and the previous token) has no open run to speak of.
    if (triggerIndex >= cursorIndex) return null;
    const trigger = text[triggerIndex];
    if (!triggers.includes(trigger)) return null;

    const boundaryOk = triggerIndex === 0 || /\s/.test(text[triggerIndex - 1]);
    if (!boundaryOk) return null;

    const query = text.slice(triggerIndex + 1, cursorIndex);
    return { trigger, triggerIndex, query };
}

/**
 * Replace the open trigger token (from `triggerIndex` through the end of its
 * query run) with `replacement`, followed by a single space — reusing one
 * that already follows. Returns the new text and the cursor index right
 * after that space.
 *
 * @param {string} text
 * @param {{triggerIndex: number}} trigger
 * @param {string} replacement
 * @returns {{text: string, cursorIndex: number}}
 */
export function applyComposerToken(text, trigger, replacement) {
    const { triggerIndex } = trigger;
    let end = triggerIndex + 1;
    while (end < text.length && !/\s/.test(text[end])) {
        end += 1;
    }
    const before = text.slice(0, triggerIndex);
    const after = text.slice(end);
    // One space after the token, unless the text already has one there.
    const inserted = /^\s/.test(after) ? replacement : `${replacement} `;
    return {
        text: `${before}${inserted}${after}`,
        cursorIndex: before.length + replacement.length + 1,
    };
}

/**
 * Find every shortcut token in `text`: a trigger character at the start of
 * the message or after whitespace, followed by a run of non-whitespace.
 * The chips the composer shows, and so what it sends, come from these.
 *
 * @param {string} text
 * @param {string[]} triggers
 * @returns {Array<{trigger: string, ref: string, start: number, end: number}>}
 */
export function findComposerTokens(text, triggers) {
    const tokens = [];
    let i = 0;
    while (i < text.length) {
        const atBoundary = i === 0 || /\s/.test(text[i - 1]);
        if (atBoundary && triggers.includes(text[i])) {
            let end = i + 1;
            while (end < text.length && !/\s/.test(text[end])) end += 1;
            if (end > i + 1) tokens.push({ trigger: text[i], ref: text.slice(i + 1, end), start: i, end });
            i = end;
        } else {
            i += 1;
        }
    }
    return tokens;
}

/**
 * Resolve a token to an item: exact id, then exact name, then a
 * case-insensitive name, id, or slug match that fits exactly one item.
 *
 * @param {string} ref
 * @param {Array<{id: string, name: string}>} items
 * @returns {object | null}
 */
export function resolveComposerItem(ref, items) {
    const byId = items.find((item) => item.id === ref);
    if (byId) return byId;
    const byName = items.find((item) => item.name === ref);
    if (byName) return byName;
    const lowered = ref.toLowerCase();
    const matches = items.filter((item) => (
        item.name.toLowerCase() === lowered || item.id.toLowerCase() === lowered || slugify(item.name) === lowered
    ));
    return matches.length === 1 ? matches[0] : null;
}

/**
 * The token to insert for `item`: its slug, or its id when the slug is empty
 * or would match another item. This is the token the model sees beside the
 * skill's heading in the system prompt, so the two read the same. The id
 * always resolves back to `item`, so the inserted token never names another.
 *
 * @param {{id: string, name: string}} item
 * @param {Array<{id: string, name: string}>} items
 * @returns {string}
 */
export function composerTokenFor(item, items) {
    const candidates = [slugify(item.name), item.id];
    return candidates.find((candidate) => candidate && resolveComposerItem(candidate, items)?.id === item.id) ?? item.id;
}

/**
 * Remove the given tokens from `text`, each with one adjoining space so no
 * double space is left behind.
 *
 * @param {string} text
 * @param {Array<{start: number, end: number}>} tokens
 * @returns {string}
 */
export function removeComposerTokens(text, tokens) {
    let result = text;
    // Right to left, so earlier offsets stay valid.
    for (const { start, end } of [...tokens].sort((a, b) => b.start - a.start)) {
        let from = start;
        let to = end;
        if (result[to] === ' ') to += 1;
        else if (from > 0 && result[from - 1] === ' ') from -= 1;
        result = result.slice(0, from) + result.slice(to);
    }
    return result;
}
