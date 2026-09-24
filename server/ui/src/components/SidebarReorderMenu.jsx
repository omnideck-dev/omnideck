import {
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from 'react';
import { createPortal } from 'react-dom';

import styles from './SidebarReorderMenu.module.css';

export default function SidebarReorderMenu({
    label,
    x,
    y,
    canMoveUp,
    canMoveDown,
    onMoveUp,
    onMoveDown,
    onUnpin = null,
    onClose,
}) {
    const menuRef = useRef(null);
    const [position, setPosition] = useState({ left: x, top: y });

    useLayoutEffect(() => {
        const menu = menuRef.current;
        if (!menu) return;
        const margin = 8;
        setPosition({
            left: Math.max(margin, Math.min(x, window.innerWidth - menu.offsetWidth - margin)),
            top: Math.max(margin, Math.min(y, window.innerHeight - menu.offsetHeight - margin)),
        });
    }, [x, y]);

    useEffect(() => {
        const closeOnOutsideClick = (event) => {
            if (!menuRef.current?.contains(event.target)) onClose();
        };
        const closeOnEscape = (event) => {
            if (event.key === 'Escape') onClose();
        };
        document.addEventListener('mousedown', closeOnOutsideClick);
        document.addEventListener('keydown', closeOnEscape);
        return () => {
            document.removeEventListener('mousedown', closeOnOutsideClick);
            document.removeEventListener('keydown', closeOnEscape);
        };
    }, [onClose]);

    return createPortal(
        <div
            ref={menuRef}
            className={styles.menu}
            role="menu"
            aria-label={`${label} actions`}
            style={position}
            onContextMenu={(event) => event.preventDefault()}
            data-testid="sidebar-reorder-menu"
        >
            <button
                type="button"
                role="menuitem"
                className={styles.item}
                disabled={!canMoveUp}
                onClick={onMoveUp}
                data-testid="sidebar-reorder-move-up"
            >
                <i className="bi bi-arrow-up" />
                Move up
            </button>
            <button
                type="button"
                role="menuitem"
                className={styles.item}
                disabled={!canMoveDown}
                onClick={onMoveDown}
                data-testid="sidebar-reorder-move-down"
            >
                <i className="bi bi-arrow-down" />
                Move down
            </button>
            {onUnpin && (
                <>
                    <div className={styles.separator} />
                    <button
                        type="button"
                        role="menuitem"
                        className={styles.item}
                        onClick={onUnpin}
                        data-testid="sidebar-reorder-unpin"
                    >
                        <i className="bi bi-pin-angle" />
                        Unpin
                    </button>
                </>
            )}
        </div>,
        document.body,
    );
}
