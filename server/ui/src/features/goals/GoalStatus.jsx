import { goalStatus, stepInProgress } from './goalStatus.js';
import styles from './GoalStatus.module.css';

export default function GoalStatus({ goal, compact = false, short = false, className = '' }) {
    const status = goalStatus(goal);
    if (!status) return null;
    const currentStep = stepInProgress(goal)?.title;
    const hover = [`Goal: ${status.label}`, goal.objective, currentStep && `Now: ${currentStep}`].filter(Boolean).join(' — ');
    const label = short ? status.shortLabel : status.label;
    return (
        <span className={[styles.status, styles[status.tone], compact && styles.compact, className].filter(Boolean).join(' ')}
            title={hover} data-testid="goal-status" data-status={status.key}>
            <i className={`bi ${status.icon} ${styles.icon}`} aria-hidden="true" />
            <span className={styles.label}>{label}</span>
        </span>
    );
}
