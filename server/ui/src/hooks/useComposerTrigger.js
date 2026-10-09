/**
 * Pure detection of a `/` or `@` composer trigger at the cursor, plus a
 * splice helper to commit a picked item back into the message text. No DOM
 * dependency — callers derive `text`/`cursorIndex` from the textarea
 * themselves, which keeps this unit-testable without rendering anything.
 */

/**
 * Find the open trigger (if any) at `cursorIndex` within `text`.
 *
 * A `/` or `@` opens a trigger only when it's the first character of the
 * message or immediately preceded by whitespace — mid-word slashes/at-signs
 * (`a/b`, `user@host`) never count. The query is the run of non-whitespace
 * characters between the trigger and the cursor; the cursor must still be
 * inside that run (not past trailing whitespace) for the trigger to be open.
 *
 * @param {string} text
 * @param {number} cursorIndex
 * @returns {null | {kind: 'skill'|'agent', triggerIndex: number, query: string}}
 */
export function detectComposerTrigger(text, cursorIndex) {
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
    const ch = text[triggerIndex];
    if (ch !== '/' && ch !== '@') return null;

    const boundaryOk = triggerIndex === 0 || /\s/.test(text[triggerIndex - 1]);
    if (!boundaryOk) return null;

    const query = text.slice(triggerIndex + 1, cursorIndex);
    return {
        kind: ch === '/' ? 'skill' : 'agent',
        triggerIndex,
        query,
    };
}

/**
 * Replace the open trigger token (from `triggerIndex` through the end of its
 * query run) with `replacement`, followed by a single trailing space.
 * Returns the new text and the cursor index right after the inserted space.
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
    const inserted = `${replacement} `;
    return {
        text: `${before}${inserted}${after}`,
        cursorIndex: before.length + inserted.length,
    };
}
