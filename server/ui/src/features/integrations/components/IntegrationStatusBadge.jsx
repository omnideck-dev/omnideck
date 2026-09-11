import StatusDot from '../../../components/StatusDot.jsx';
import styles from '../IntegrationsView.module.css';

export const STATUS_VIEW = {
    running: { dot: 'ready', label: 'connected', badge: 'badgeSuccess' },
    auth_failed: { dot: 'error', label: 'auth failed', badge: 'badgeDanger' },
    broken: { dot: 'error', label: 'not running', badge: 'badgeDanger' },
};

export default function IntegrationStatusBadge({ state }) {
    // Unknown runtime states fail closed visually; never label an unfamiliar
    // supervisor state as connected.
    const view = STATUS_VIEW[state] || STATUS_VIEW.broken;
    return (
        <span className={`${styles.badge} ${styles[view.badge]}`}>
            <StatusDot status={view.dot} /> {view.label}
        </span>
    );
}
