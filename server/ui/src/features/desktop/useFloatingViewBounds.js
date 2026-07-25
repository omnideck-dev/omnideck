import {
    useCallback,
    useEffect,
    useRef,
    useState,
} from 'react';

const MIN_VISIBLE_TITLE_WIDTH = 120;
const MIN_VISIBLE_TITLE_HEIGHT = 36;

/**
 * Keep high-frequency floating geometry local to one View host.
 *
 * Drag commits once on pointer-up. Native CSS resizing commits after a short
 * idle period because browsers do not expose a reliable resize-end event.
 */
export default function useFloatingViewBounds({
    viewId,
    floatingView,
    fullscreen,
    commands,
    hostRef,
}) {
    const dragRef = useRef(null);
    const resizeCommitRef = useRef(null);
    const boundsRef = useRef(floatingView);
    const [liveBounds, setLiveBounds] = useState(floatingView);
    const floating = Boolean(floatingView);

    const updateLiveBounds = useCallback((bounds) => {
        const next = {
            ...(boundsRef.current || {}),
            ...bounds,
        };
        boundsRef.current = next;
        setLiveBounds(next);
    }, []);

    useEffect(() => {
        // A focus update can arrive during pointer interaction. Do not replace
        // newer local geometry with the older reducer snapshot in that case.
        if (!dragRef.current && !resizeCommitRef.current) {
            boundsRef.current = floatingView;
            setLiveBounds(floatingView);
        }
    }, [floatingView]);

    const clampPosition = useCallback((x, y) => {
        const viewportWidth = window.visualViewport?.width
            || window.innerWidth
            || document.documentElement.clientWidth;
        const viewportHeight = window.visualViewport?.height
            || window.innerHeight
            || document.documentElement.clientHeight;
        if (!viewportWidth || !viewportHeight) {
            return { x: Math.max(0, x), y: Math.max(0, y) };
        }
        return {
            x: Math.max(
                0,
                Math.min(x, viewportWidth - MIN_VISIBLE_TITLE_WIDTH),
            ),
            y: Math.max(
                0,
                Math.min(y, viewportHeight - MIN_VISIBLE_TITLE_HEIGHT),
            ),
        };
    }, []);

    const startDrag = useCallback((event) => {
        const current = boundsRef.current || floatingView;
        if (
            !current
            || fullscreen
            || event.button !== 0
            || event.target.closest?.('button')
        ) {
            return;
        }
        event.preventDefault();
        dragRef.current = {
            pointerId: event.pointerId,
            startX: event.clientX,
            startY: event.clientY,
            x: current.x,
            y: current.y,
        };
        event.currentTarget.setPointerCapture?.(event.pointerId);
    }, [floatingView, fullscreen]);

    const drag = useCallback((event) => {
        const current = dragRef.current;
        if (!current || current.pointerId !== event.pointerId) return;
        updateLiveBounds(clampPosition(
            current.x + event.clientX - current.startX,
            current.y + event.clientY - current.startY,
        ));
    }, [clampPosition, updateLiveBounds]);

    const endDrag = useCallback((event) => {
        if (dragRef.current?.pointerId !== event.pointerId) return;
        dragRef.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        const bounds = boundsRef.current;
        if (bounds) {
            commands.updateFloatingBounds(viewId, {
                x: bounds.x,
                y: bounds.y,
            });
        }
    }, [commands.updateFloatingBounds, viewId]);

    useEffect(() => {
        if (!floating || fullscreen) return undefined;
        const keepTitleReachable = () => {
            const current = boundsRef.current;
            if (!current) return;
            const position = clampPosition(current.x, current.y);
            if (
                position.x !== current.x
                || position.y !== current.y
            ) {
                updateLiveBounds(position);
                commands.updateFloatingBounds(viewId, position);
            }
        };
        keepTitleReachable();
        window.addEventListener('resize', keepTitleReachable);
        return () => window.removeEventListener('resize', keepTitleReachable);
    }, [
        clampPosition,
        commands.updateFloatingBounds,
        floating,
        fullscreen,
        updateLiveBounds,
        viewId,
    ]);

    useEffect(() => {
        if (!floating || fullscreen || typeof ResizeObserver === 'undefined') {
            return undefined;
        }
        const host = hostRef.current;
        if (!host) return undefined;
        const observer = new ResizeObserver(() => {
            const width = host.offsetWidth;
            const height = host.offsetHeight;
            const current = boundsRef.current;
            if (
                width <= 0
                || height <= 0
                || !current
                || (
                    Math.abs(width - current.width) <= 1
                    && Math.abs(height - current.height) <= 1
                )
            ) {
                return;
            }

            updateLiveBounds({ width, height });
            clearTimeout(resizeCommitRef.current);
            resizeCommitRef.current = setTimeout(() => {
                resizeCommitRef.current = null;
                commands.updateFloatingBounds(viewId, { width, height });
            }, 150);
        });
        observer.observe(host);
        return () => {
            observer.disconnect();
            if (resizeCommitRef.current) {
                clearTimeout(resizeCommitRef.current);
                const bounds = boundsRef.current;
                if (bounds) {
                    // Docking, closing, or entering fullscreen can tear down
                    // the observer before its debounce expires. Flush the
                    // last observed native resize instead of discarding it.
                    commands.updateFloatingBounds(viewId, {
                        width: bounds.width,
                        height: bounds.height,
                    });
                }
            }
            resizeCommitRef.current = null;
        };
    }, [
        commands.updateFloatingBounds,
        floating,
        fullscreen,
        hostRef,
        updateLiveBounds,
        viewId,
    ]);

    return {
        bounds: liveBounds || floatingView,
        drag,
        endDrag,
        startDrag,
    };
}
