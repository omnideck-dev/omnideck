/**
 * Kebab-case a display name for use as a composer token.
 *
 * Must stay behaviorally identical to the backend's copy of this algorithm
 * (`agent_runtime/_composer_tokens.py`, `_slugify`) — there's no shared
 * runtime between the two, so any drift here silently breaks resolution for
 * a token this function already produced.
 *
 * @param {string} text
 * @returns {string}
 */
export function slugify(text) {
    return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}
