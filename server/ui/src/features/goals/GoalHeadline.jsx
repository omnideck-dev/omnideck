import Button from '../../components/primitives/Button.jsx';
import { goalStatus, planProgress, stepInProgress } from './goalStatus.js';
import styles from './GoalHeadline.module.css';
import toneStyles from './GoalStatus.module.css';

/** The chat header's goal button. It opens the Goal tab; plan details sit in the hover text. */
export default function GoalHeadline({ goal, onOpen }) {
    const status = goalStatus(goal);
    if (!status) return null;
    const { done, total } = planProgress(goal);
    const step = goal.running ? stepInProgress(goal)?.title : null;
    const hover = [total ? `${done} of ${total} steps done` : '', step && `Now: ${step}`, 'Open goal details'].filter(Boolean).join('. ');
    return <Button variant="ghost" className={styles.headline} onClick={onOpen}
        aria-label={`Goal: ${status.label}. Open goal details`} title={hover} data-testid="goal-headline" data-status={status.key}>
        <i className={`bi bi-bullseye ${toneStyles[status.tone]}`} aria-hidden="true" />
        <span className={`${styles.full} ${toneStyles[status.tone]}`}>{status.label}</span>
        <span className={`${styles.short} ${toneStyles[status.tone]}`}>{status.shortLabel}</span>
    </Button>;
}
