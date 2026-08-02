import { createContext, useContext, useMemo } from 'react';

const OmnideckHostContext = createContext(undefined);

function hostOnThisPage() {
    return (typeof window === 'undefined' ? null : window.omnideckHost) || null;
}

/**
 * The desktop application's bridge, or null when there is no desktop
 * application.
 *
 * Omnideck runs in three places — the desktop application, a plain browser, and
 * a container started from the command line — and only the first can install
 * anything or act on the window around the page. Its absence is what tells a
 * component to render nothing, so that check belongs somewhere a test can set
 * rather than in a global each component reaches into for itself.
 *
 * `host` is for tests and stories; left alone, the page is asked.
 */
export function OmnideckHostProvider({ children, host }) {
    const value = useMemo(
        () => (host === undefined ? hostOnThisPage() : host),
        [host],
    );
    return (
        <OmnideckHostContext.Provider value={value}>
            {children}
        </OmnideckHostContext.Provider>
    );
}

/** The bridge, or null. Null is an ordinary answer, not a missing provider. */
export function useOmnideckHost() {
    const value = useContext(OmnideckHostContext);
    if (value === undefined) {
        throw new Error('useOmnideckHost must be used within OmnideckHostProvider');
    }
    return value;
}

/** Whether a host is present, for deciding what is worth rendering. */
export function useIsHosted() {
    return Boolean(useOmnideckHost());
}
