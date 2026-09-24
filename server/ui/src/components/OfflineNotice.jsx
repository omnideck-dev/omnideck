import styles from './OfflineNotice.module.css';

/** Connection status shown beside controls that require the server. */
export default function OfflineNotice({ description, className = '' }) {
    return (
        <div
            className={[styles.notice, className].filter(Boolean).join(' ')}
            data-testid="connection-status"
            role="status"
        >
            <i className="bi bi-wifi-off" aria-hidden="true" />
            <strong>Offline</strong>
            <span>{description}</span>
        </div>
    );
}
