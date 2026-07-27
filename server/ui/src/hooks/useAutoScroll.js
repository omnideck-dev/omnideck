import {
    useRef,
    useEffect,
    useLayoutEffect,
    useCallback,
    useState,
} from 'react';

const NEAR_BOTTOM_PX = 150;

/**
 * Auto-scroll a container to the bottom when dependencies change,
 * unless the user has manually scrolled up.
 *
 * @param {Array} deps — Dependency array that triggers a scroll check.
 * @param {boolean} [enabled=true] — Whether auto-scroll is active (e.g. only when agent is running).
 * @returns {{ ref, contentRef, onScroll, resetScroll, isAtBottom, scrollToBottom }}
 *   - ref: Attach to the scrollable container element.
 *   - contentRef: Optionally attach to its content wrapper so late size
 *     changes (such as images loading) can keep a followed view pinned.
 *   - onScroll: Attach as the container's onScroll handler.
 *   - resetScroll: Call to re-enable auto-scroll (e.g. when switching views).
 *   - isAtBottom: Whether the viewport is at (or close to) the latest content.
 *   - scrollToBottom: Immediately move to the latest content and resume auto-scroll.
 */
export default function useAutoScroll(deps, enabled = true) {
    const ref = useRef(null);
    const contentRef = useRef(null);
    const userScrolledRef = useRef(false);
    const [isAtBottom, setIsAtBottom] = useState(true);

    const onScroll = useCallback(() => {
        const el = ref.current;
        if (!el) return;
        const nearBottom = (
            el.scrollHeight - el.scrollTop - el.clientHeight
        ) < NEAR_BOTTOM_PX;
        userScrolledRef.current = !nearBottom;
        setIsAtBottom(nearBottom);
    }, []);

    const resetScroll = useCallback(() => {
        userScrolledRef.current = false;
        setIsAtBottom(true);
    }, []);

    const scrollToBottom = useCallback(() => {
        const el = ref.current;
        if (!el) return;

        userScrolledRef.current = false;
        // Force an instant move even if another consumer opts into smooth
        // programmatic scrolling in its own styles.
        const previousScrollBehavior = el.style.scrollBehavior;
        el.style.scrollBehavior = 'auto';
        el.scrollTop = el.scrollHeight;
        el.style.scrollBehavior = previousScrollBehavior;
        setIsAtBottom(true);
    }, []);

    // Pin before the browser paints. The scroll container must use instant
    // programmatic scrolling: a smooth animation emits intermediate scroll
    // events that look like the reader moved away from the bottom.
    useLayoutEffect(() => {
        if (!enabled || userScrolledRef.current) return;
        scrollToBottom();
    }, deps); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const content = contentRef.current;
        if (!content || typeof ResizeObserver === 'undefined') return undefined;

        const observer = new ResizeObserver(() => {
            if (!enabled || userScrolledRef.current) return;
            scrollToBottom();
        });
        observer.observe(content);
        return () => observer.disconnect();
    }, [enabled, scrollToBottom]);

    return {
        ref,
        contentRef,
        onScroll,
        resetScroll,
        isAtBottom,
        scrollToBottom,
    };
}
