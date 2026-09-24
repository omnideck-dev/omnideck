import { useEffect, useState } from 'react';

const MOBILE_QUERY = '(max-width: 768px)';

function readMatches() {
    // jsdom (unit tests) has no matchMedia unless a test mocks it.
    return window.matchMedia?.(MOBILE_QUERY)?.matches ?? false;
}

/**
 * Tracks whether the viewport currently matches the mobile breakpoint,
 * updating on resize/rotation rather than just at mount.
 */
export default function useIsMobileViewport() {
    const [isMobile, setIsMobile] = useState(readMatches);

    useEffect(() => {
        const mql = window.matchMedia?.(MOBILE_QUERY);
        if (!mql) return undefined;
        const handleChange = (event) => setIsMobile(event.matches);
        mql.addEventListener('change', handleChange);
        return () => mql.removeEventListener('change', handleChange);
    }, []);

    return isMobile;
}
