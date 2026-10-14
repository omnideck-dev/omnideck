import { useRef, useEffect, useCallback } from 'react';

// Cache-busting an iframe's `src` to pick up on-disk changes forces a full
// navigation, which resets the embedded document's scroll to the top. This
// remembers the last scroll position across those reloads (so auto-refresh
// doesn't yank a reader back to the top) while still resetting to the top
// when `resetKey` changes, i.e. when the previewed file itself changes.
export default function useIframeScrollPreservation(iframeRef, resetKey) {
    const scrollRef = useRef({ x: 0, y: 0 });

    useEffect(() => {
        scrollRef.current = { x: 0, y: 0 };
    }, [resetKey]);

    return useCallback(() => {
        const win = iframeRef.current?.contentWindow;
        if (!win) return;
        try {
            win.scrollTo(scrollRef.current.x, scrollRef.current.y);
            // Each reload navigates to a fresh document/window, so this listener
            // is naturally discarded with it — nothing to clean up on unmount.
            win.addEventListener('scroll', () => {
                scrollRef.current = { x: win.scrollX, y: win.scrollY };
            });
        } catch {
            // Cross-origin frame — shouldn't happen for same-origin previews, but
            // scripting a foreign window throws, so just leave scroll as-is.
        }
    }, [iframeRef, resetKey]);
}
