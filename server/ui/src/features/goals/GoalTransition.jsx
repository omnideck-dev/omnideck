import { formatClockTime, formatRunTime, plural, statusTone } from './goalStatus.js';
import styles from './GoalTransition.module.css';

const DIVIDERS = {
    run: { icon: 'bi-play-circle', tone: 'accent', label: () => 'Goal run', detail: (event) => event.step },
    scheduled: { ...statusTone('scheduled'), label: (event) => `Resumes ${formatRunTime(event.resumeAt)}` },
    waiting: {
        ...statusTone('waiting'), label: () => 'Waiting for you',
        detail: (event) => (event.questionCount ? plural(event.questionCount, 'question') : ''),
    },
    error: { ...statusTone('error'), label: () => 'Stopped by an error' },
    completed: { ...statusTone('done'), label: () => 'Goal done' },
};

export default function GoalTransition({ event }) {
    const divider = DIVIDERS[event.transition];
    if (!divider) return null;
    const { icon, tone } = divider;
    const label = divider.label(event);
    const detail = divider.detail?.(event) || '';
    const time = formatClockTime(event.timestamp);
    return <div className={styles.row} data-testid="goal-transition" data-transition={event.transition}>
        <span className={styles.content} data-time={`· ${time}`}>
            <i className={`bi ${icon} ${styles.icon} ${styles[tone]}`} aria-hidden="true" />
            <span className={styles.label}>{label}</span>
            {detail && <span className={styles.detail}><span aria-hidden="true">· </span>{detail}</span>}
            <time className={styles.time} dateTime={event.timestamp} title={new Date(event.timestamp).toLocaleString()}>
                <span aria-hidden="true">· </span>{time}
            </time>
        </span>
    </div>;
}
