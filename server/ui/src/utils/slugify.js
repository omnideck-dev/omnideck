/**
 * Kebab-case a display name for use as a composer token.
 *
 * Must stay behaviorally identical to the server's copy used to resolve
 * composer tokens — there's no shared runtime between the two, so any drift
 * here silently breaks resolution for a token this function produced.
 *
 * @param {string} text
 * @returns {string}
 */
export function slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}
