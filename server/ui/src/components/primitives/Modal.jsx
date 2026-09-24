import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';

import styles from './Modal.module.css';

/**
 * Modal scaffold: a scrim + centered panel with the shared dialog chrome.
 * Owns the cross-cutting behaviors every modal needs — backdrop-click and
 * Escape to dismiss, dialog semantics, and moving focus into the panel on
 * open — so callers supply only the contents. `width` overrides the default
 * panel width for wider modals; `labelledBy` points at the id of the caller's
 * title element for accessible naming.
 */
export default function Modal({
    onClose,
    children,
    width,
    labelledBy,
    className = '',
    testId,
}) {
    const panelRef = useRef(null);

    useEffect(() => {
        function onKey(e) {
            if (e.key === 'Escape') onClose?.();
        }
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [onClose]);

    // Pull focus off the triggering control and into the panel so Escape and
    // tabbing start from inside the dialog.
    useEffect(() => {
        panelRef.current?.focus();
    }, []);

    const modal = (
        <div
            className={styles.scrim}
            onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
        >
            <div
                ref={panelRef}
                className={`${styles.modal} ${className}`}
                role="dialog"
                aria-modal="true"
                aria-labelledby={labelledBy}
                tabIndex={-1}
                style={width ? { width } : undefined}
                data-testid={testId}
            >
                {children}
            </div>
        </div>
    );

    // View hosts deliberately clip their content so inactive, floating, and
    // split views cannot paint into neighboring regions. A modal is global UI,
    // however, and must escape that containment boundary. Portaling to body
    // also keeps fixed positioning relative to the viewport when an ancestor
    // establishes a transformed or positioned containing block.
    return createPortal(modal, document.body);
}
