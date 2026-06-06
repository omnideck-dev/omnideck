import { useEffect, useCallback } from 'react';
import styles from './FullscreenPreview.module.css';
import IconButton from './primitives/IconButton.jsx';

export default function FullscreenPreview({ title, onClose, headerActions, children }) {
    const handleKeyDown = useCallback((e) => {
        if (e.key === 'Escape') {
            onClose();
        }
    }, [onClose]);

    useEffect(() => {
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [handleKeyDown]);

    return (
        <div className={styles.fullscreenPreview} data-testid="fullscreen-preview">
            <div className={styles.header}>
                <div className={styles.headerLeft} />

                <div className={styles.headerCenter}>
                    {title && (
                        <span
                            className={styles.title}
                            title={typeof title === 'string' ? title : undefined}
                        >
                            {title}
                        </span>
                    )}
                </div>

                <div className={styles.headerRight}>
                    {headerActions}
                    <IconButton
                        size="sm"
                        onClick={onClose}
                        title="Exit fullscreen"
                        aria-label="Exit fullscreen"
                        data-testid="fullscreen-back"
                    >
                        <i className="bi bi-arrows-angle-contract" style={{ fontSize: 14 }} />
                    </IconButton>
                </div>
            </div>

            <div className={styles.content}>
                {children}
            </div>
        </div>
    );
}
