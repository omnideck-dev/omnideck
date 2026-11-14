import Button from '../../components/primitives/Button.jsx';
import GoalStatus from './GoalStatus.jsx';
import styles from './GoalHeadline.module.css';

/** The chat header's goal status. It opens the Goal tab; plan details sit in the hover text. */
export default function GoalHeadline({ goal, onOpen }) {
    const plan = goal.plan || [];
    const finished = plan.filter((step) => ['done', 'skipped'].includes(step.status)).length;
    const currentStep = goal.running ? plan.find((step) => step.status === 'in_progress')?.title : null;
    const progress = plan.length ? `${finished} of ${plan.length} steps done` : '';
    const hover = [progress, currentStep && `Now: ${currentStep}`, 'Open goal details'].filter(Boolean).join('. ');

    return <Button variant="ghost" className={styles.headline} onClick={onOpen} aria-label="Open goal details" title={hover}>
        <span className={styles.goal}>Goal</span>
        <span className={styles.full}><GoalStatus goal={goal} /></span>
        <span className={styles.short}><GoalStatus goal={goal} short /></span>
        <i className={`bi bi-chevron-right ${styles.chevron}`} aria-hidden="true" />
    </Button>;
}
