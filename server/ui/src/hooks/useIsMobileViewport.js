import { useSyncExternalStore } from 'react';

const MOBILE_QUERY = '(max-width: 768px)';

let cachedMql = null;
let cachedMatchMedia = null;

function getMediaQueryList() {
    // jsdom (unit tests) has no matchMedia unless a test mocks it.
    const matchMedia = window.matchMedia;
    if (!matchMedia) return null;
    // Cache keyed on the matchMedia reference itself, not just presence: it
    // stays stable in production so this avoids allocating a fresh
    // MediaQueryList on every render, while still picking up a replacement
    // mock across tests that reassign window.matchMedia.
    if (cachedMatchMedia !== matchMedia) {
        cachedMql = matchMedia(MOBILE_QUERY);
        cachedMatchMedia = matchMedia;
    }
    return cachedMql;
}

function subscribe(onChange) {
    const mql = getMediaQueryList();
    if (!mql) return () => {};
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
}

function getSnapshot() {
    return getMediaQueryList()?.matches ?? false;
}

/**
 * Tracks whether the viewport currently matches the mobile breakpoint,
 * updating on resize/rotation rather than just at mount.
 *
 * Backed by useSyncExternalStore rather than useState+useEffect: a plain
 * useState initializer only reads the match once at mount, and the 'change'
 * listener isn't attached until a later effect, so a breakpoint crossing in
 * that gap is silently missed. useSyncExternalStore re-checks the snapshot
 * when it subscribes, closing that window.
 */
export default function useIsMobileViewport() {
    return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}
