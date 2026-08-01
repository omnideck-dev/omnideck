import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import styles from './Popover.module.css';

const DEFAULT_VIEWPORT_MARGIN = 8;
const DEFAULT_GAP = 6;
const DEFAULT_MAX_HEIGHT = 360;

function horizontalPosition(rect, width, align, minLeft, maxLeft) {
    const start = rect.left;
    const end = rect.right - width;
    const center = rect.left + (rect.width - width) / 2;
    const preferred = align === 'end' ? end : align === 'center' ? center : start;
    const fallback = align === 'end' ? start : end;

    if (preferred >= minLeft && preferred <= maxLeft) return preferred;
    if (align !== 'center' && fallback >= minLeft && fallback <= maxLeft) return fallback;
    return Math.min(Math.max(minLeft, preferred), maxLeft);
}

/**
 * Viewport-aware anchored overlay.
 *
 * Popovers are portaled to document.body so a scroll pane or split view cannot
 * clip them. In auto placement they prefer the trigger's lower edge, but flip
 * above it when the room below falls under the caller's useful-height threshold
 * and the upper side has more room. Their maximum height is capped to the chosen
 * side of the viewport; callers should make their content scroll within that
 * height.
 */
export default function Popover({
    anchorRef,
    returnFocusRef = anchorRef,
    onClose,
    children,
    className = '',
    align = 'start',
    placement = 'auto',
    width,
    maxHeight = DEFAULT_MAX_HEIGHT,
    flipThreshold = maxHeight,
    gap = DEFAULT_GAP,
    viewportMargin = DEFAULT_VIEWPORT_MARGIN,
    role,
    ariaLabel,
    testId,
}) {
    const popoverRef = useRef(null);
    const [position, setPosition] = useState(null);

    useLayoutEffect(() => {
        const updatePosition = () => {
            const anchor = anchorRef.current;
            if (!anchor) return;

            const rect = anchor.getBoundingClientRect();
            const availableWidth = Math.max(0, window.innerWidth - (viewportMargin * 2));
            const resolvedWidth = Math.min(width || rect.width, availableWidth);
            const maxLeft = Math.max(
                viewportMargin,
                window.innerWidth - viewportMargin - resolvedWidth,
            );
            const left = horizontalPosition(
                rect,
                resolvedWidth,
                align,
                viewportMargin,
                maxLeft,
            );

            const roomBelow = Math.max(
                0,
                window.innerHeight - rect.bottom - gap - viewportMargin,
            );
            const roomAbove = Math.max(0, rect.top - gap - viewportMargin);
            const minimumRoomBelow = Math.min(maxHeight, Math.max(0, flipThreshold));
            const resolvedPlacement = placement === 'auto'
                ? (roomBelow < minimumRoomBelow && roomAbove > roomBelow ? 'top' : 'bottom')
                : placement;
            const availableHeight = resolvedPlacement === 'top' ? roomAbove : roomBelow;

            setPosition({
                left,
                width: resolvedWidth,
                maxHeight: Math.min(maxHeight, availableHeight),
                placement: resolvedPlacement,
                edge: resolvedPlacement === 'top'
                    ? window.innerHeight - rect.top + gap
                    : rect.bottom + gap,
            });
        };

        updatePosition();
        window.addEventListener('resize', updatePosition);
        window.addEventListener('scroll', updatePosition, true);

        const anchor = anchorRef.current;
        const observer = anchor && typeof ResizeObserver !== 'undefined'
            ? new ResizeObserver(updatePosition)
            : null;
        observer?.observe(anchor);

        return () => {
            observer?.disconnect();
            window.removeEventListener('resize', updatePosition);
            window.removeEventListener('scroll', updatePosition, true);
        };
    }, [align, anchorRef, flipThreshold, gap, maxHeight, placement, viewportMargin, width]);

    useEffect(() => {
        const handleOutsideMouseDown = (event) => {
            if (anchorRef.current?.contains(event.target)) return;
            if (popoverRef.current?.contains(event.target)) return;
            onClose?.();
        };
        const handleKeyDown = (event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            onClose?.();
            returnFocusRef.current?.focus();
        };
        document.addEventListener('mousedown', handleOutsideMouseDown);
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('mousedown', handleOutsideMouseDown);
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [anchorRef, onClose, returnFocusRef]);

    const positionStyle = position
        ? {
            left: `${position.left}px`,
            width: `${position.width}px`,
            maxHeight: `${position.maxHeight}px`,
            ...(position.placement === 'top'
                ? { bottom: `${position.edge}px` }
                : { top: `${position.edge}px` }),
        }
        : { visibility: 'hidden' };

    return createPortal(
        <div
            ref={popoverRef}
            className={`${styles.popover} ${className}`}
            style={positionStyle}
            role={role}
            aria-label={ariaLabel}
            data-placement={position?.placement}
            data-testid={testId}
        >
            {children}
        </div>,
        document.body,
    );
}
