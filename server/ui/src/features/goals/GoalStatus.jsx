import { goalStatusLabel } from './GoalsState.jsx';
import styles from './GoalPanel.module.css';

export default function GoalStatus({ goal, compact = false }) {
    if (!goal) return null;
    const label = goalStatusLabel(goal);
    const running = goal.running && !['completed', 'paused', 'cancelled'].includes(goal.status);
    const icon = running ? 'bi-arrow-repeat' : ({ scheduled: 'bi-clock', needs_input: 'bi-chat-left-text', paused: 'bi-pause-circle', completed: 'bi-check-circle', cancelled: 'bi-x-circle' })[goal.status] || 'bi-bullseye';
    return (
        <span className={`${styles.status} ${styles[running ? 'running' : goal.status] || ''} ${compact ? styles.compact : ''}`} title={`Goal: ${label}${goal.objective ? ` — ${goal.objective}` : ''}`} aria-label={`Goal: ${label}`} data-testid="goal-status">
            <i className={`bi ${icon}`} aria-hidden="true" />
            <span>{label}</span>
        </span>
    );
}
