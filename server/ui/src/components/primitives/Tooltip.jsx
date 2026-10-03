import { useCallback, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import styles from './Tooltip.module.css';

/**
 * Hover/focus tooltip that wraps arbitrary children without affecting their
 * layout (`display: contents` on the wrapper). Portaled to `document.body`
 * and positioned from the wrapper's `getBoundingClientRect()` so it escapes
 * any clipping ancestor, the same approach as `Popover`.
 *
 * Promoted out of `ModelSettingsPanel`'s local `InfoTip` once a second caller
 * (the composer autocomplete's skill/agent rows) needed the identical
 * show/hide-on-hover behavior.
 */
export default function Tooltip({ text, placement = 'right', children }) {
    const wrapRef = useRef(null);
    const [pos, setPos] = useState(null);

    const show = useCallback(() => {
        const el = wrapRef.current;
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
