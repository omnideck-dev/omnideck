import { formatRunTime, plural, statusTone } from './goalStatus.js';
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

function formatTime(value) {
    return new Date(value).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/** A one-line goal divider. Its time shows on hover; day headers carry the date. */
export default function GoalTransition({ event }) {
    const divider = DIVIDERS[event.transition];
    if (!divider) return null;
    const { icon, tone } = divider;
    const label = divider.label(event);
    const detail = divider.detail?.(event) || '';
    const time = formatTime(event.timestamp);
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

function dayLabel(value) {
    const date = new Date(value);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return 'Today';
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

/** A small header where the day changes in a goal chat or goal history. */
export function DayHeader({ timestamp }) {
    return <div className={styles.day} data-testid="day-header" role="separator" aria-label={dayLabel(timestamp)}>
        <time dateTime={timestamp}>{dayLabel(timestamp)}</time>
    </div>;
}
