import { getConnectionAdapter } from '../catalog/adapterRegistry.js';
import styles from './IntegrationRowSummary.module.css';

export default function IntegrationRowSummary({ record }) {
    if (record.state === 'running') {
        const count = (record.operation_grants || []).length;
        return count === 0 ? 'No tools selected' : `${count} ${count === 1 ? 'tool' : 'tools'} selected`;
    }
    const label = record.state === 'auth_failed'
        ? getConnectionAdapter(record.slug).updateAction
        : record.state === 'broken' ? 'Connection unavailable' : 'Couldn’t check connection';
    return (
        <span className={styles.issue} data-testid="integration-issue">
            <i className="bi bi-exclamation-triangle" aria-hidden="true" />
            {label}
        </span>
    );
}
