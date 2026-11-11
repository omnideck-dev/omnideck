/**
 * Kebab-case a display name for use as a composer token.
 *
 * Must stay behaviorally identical to the server's copy, which labels each
 * skill with its token in the system prompt — there's no shared runtime
 * between the two, so any drift leaves the token a user typed different
 * from the one the model sees.
 *
 * @param {string} text
 * @returns {string}
 */
export function slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}
