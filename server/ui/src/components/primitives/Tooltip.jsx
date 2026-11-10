import { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import styles from './Tooltip.module.css';

/**
 * Hover/focus tooltip that wraps a single child element without affecting
 * its layout (`display: contents` on the wrapper). Portaled to
 * `document.body` and positioned from the child's bounding rect so it
 * escapes any clipping ancestor, the same approach as `Popover`.
 */
export default function Tooltip({ text, placement = 'right', children }) {
    const wrapRef = useRef(null);
    const [pos, setPos] = useState(null);

    const show = useCallback(() => {
        // A `display: contents` wrapper has no box of its own (its rect is
        // all zeros), so measure the wrapped element instead.
        const el = wrapRef.current?.firstElementChild;
        if (!el) return;
        const rect = el.getBoundingClientRect();
        if (placement === 'top') {
            setPos({ left: rect.left + rect.width / 2, top: rect.top - 8, transform: 'translate(-50%, -100%)' });
        } else {
            setPos({ left: rect.right + 8, top: rect.top + rect.height / 2, transform: 'translateY(-50%)' });
        }
    }, [placement]);

    const hide = useCallback(() => setPos(null), []);

    if (!text) return children;

    return (
        <span
            ref={wrapRef}
            className={styles.wrap}
            onMouseEnter={show}
            onMouseLeave={hide}
            onFocus={show}
            onBlur={hide}
        >
            {children}
            {pos && createPortal(
                <span
                    className={styles.tooltip}
                    style={{ left: pos.left, top: pos.top, transform: pos.transform }}
                >
                    {text}
                </span>,
                document.body,
            )}
        </span>
    );
}
