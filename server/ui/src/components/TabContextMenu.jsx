import {
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react';
import { createPortal } from 'react-dom';

import styles from './TabContextMenu.module.css';

const VIEWPORT_MARGIN = 8;

/** Portaled command menu for a tab targeted by mouse or keyboard. */
export default function TabContextMenu({
    actions,
    position,
    testid,
    onClose,
}) {
    const menuRef = useRef(null);
    const [resolvedPosition, setResolvedPosition] = useState(null);

    useLayoutEffect(() => {
        const menu = menuRef.current;
        if (!menu) return;
        const left = Math.min(
            position.x,
            window.innerWidth - menu.offsetWidth - VIEWPORT_MARGIN,
        );
        const top = Math.min(
            position.y,
            window.innerHeight - menu.offsetHeight - VIEWPORT_MARGIN,
        );
        setResolvedPosition({
            left: Math.max(VIEWPORT_MARGIN, left),
            top: Math.max(VIEWPORT_MARGIN, top),
        });
    }, [position]);

    useLayoutEffect(() => {
        if (!resolvedPosition) return;
        menuRef.current?.querySelector('button:not(:disabled)')?.focus();
    }, [resolvedPosition]);

    useEffect(() => {
        const handleOutsideMouseDown = (event) => {
            if (!menuRef.current?.contains(event.target)) onClose();
        };
        const handleKeyDown = (event) => {
            if (event.key === 'Escape') {
                event.preventDefault();
                onClose();
            }
        };
        document.addEventListener('mousedown', handleOutsideMouseDown);
        document.addEventListener('keydown', handleKeyDown);
        return () => {
            document.removeEventListener('mousedown', handleOutsideMouseDown);
            document.removeEventListener('keydown', handleKeyDown);
        };
    }, [onClose]);

    const handleMenuKeyDown = (event) => {
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = Array.from(
            menuRef.current?.querySelectorAll('button:not(:disabled)') || [],
        );
        if (!items.length) return;
        const currentIndex = items.indexOf(document.activeElement);
        const nextIndex = {
            ArrowDown: currentIndex < 0 ? 0 : (currentIndex + 1) % items.length,
            ArrowUp: currentIndex < 0
                ? items.length - 1
                : (currentIndex - 1 + items.length) % items.length,
            Home: 0,
            End: items.length - 1,
        }[event.key];
        items[nextIndex].focus();
    };

    return createPortal(
        <div
            ref={menuRef}
            className={styles.menu}
            role="menu"
            aria-label="Tab actions"
            data-testid={testid}
            style={resolvedPosition || { visibility: 'hidden' }}
            onKeyDown={handleMenuKeyDown}
            onContextMenu={(event) => event.preventDefault()}
        >
            {actions.map((action) => (
                <div key={action.id}>
                    {action.separatorBefore && (
                        <div className={styles.separator} role="separator" />
                    )}
                    <button
                        type="button"
                        role="menuitem"
                        className={styles.item}
                        disabled={action.disabled}
                        onClick={() => {
                            onClose();
                            action.execute();
                        }}
                        data-testid={
                            action.testid
                            || `tab-context-action-${action.id}`
                        }
                    >
                        <i className={`bi ${action.icon}`} aria-hidden="true" />
                        <span
                            data-testid={
                                action.testid
                                    ? `tab-context-action-${action.id}`
                                    : undefined
                            }
                        >
                            {action.label}
                        </span>
                    </button>
                </div>
            ))}
        </div>,
        document.body,
    );
}
