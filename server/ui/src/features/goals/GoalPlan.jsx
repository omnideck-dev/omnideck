import { planProgress } from './goalStatus.js';
import styles from './GoalPlan.module.css';

const STEPS = {
    done: { icon: 'bi-check-circle', text: 'Done' },
    skipped: { icon: 'bi-dash-circle', text: 'Skipped' },
    in_progress: { icon: 'bi-record-circle', text: 'In progress' },
    blocked: { icon: 'bi-exclamation-circle', text: 'Blocked' },
    pending: { icon: 'bi-circle', text: 'Not started' },
};

export default function GoalPlan({ goal }) {
    const plan = goal.plan || [];
    if (!plan.length) return <p className={styles.description}>The agent will build its plan as it works.</p>;
    const { done, total } = planProgress(goal);
    const titles = Object.fromEntries(plan.map((step) => [step.id, step.title]));
    return <section className={styles.block} aria-label="Plan">
        <div className={styles.progressRow}>
            <h3 className={styles.label}>Plan</h3>
            <span className={styles.bar} role="progressbar" aria-label="Plan progress" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
                <span className={styles.barFill} style={{ width: `${Math.round((done / total) * 100)}%` }} />
            </span>
            <span className={styles.progressCount}>{done} of {total}</span>
        </div>
        <ol className={styles.plan}>{plan.map((step) => {
            const shown = STEPS[step.status] || STEPS.pending;
            return <li key={step.id} className={`${styles.planItem} ${styles[step.status] || ''}`}>
                <i className={`bi ${shown.icon}`} aria-hidden="true" />
                <div>
                    <span><span className={styles.hidden}>{shown.text}: </span>{step.title}</span>
                    {step.status === 'in_progress' && <span className={styles.nowTag} aria-hidden="true">Now</span>}
                    {step.status === 'blocked' && <span className={styles.stepState} aria-hidden="true">Blocked</span>}
                    {step.status === 'skipped' && <span className={styles.stepState} aria-hidden="true">Skipped</span>}
                    {step.depends_on?.length > 0 && <span className={styles.stepNote}>Depends on: {step.depends_on.map((id) => titles[id] || id).join(', ')}</span>}
                    {step.notes && <span className={styles.stepNote}>{step.notes}</span>}
                </div>
            </li>;
        })}</ol>
    </section>;
}
