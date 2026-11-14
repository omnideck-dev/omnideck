import { formatRunTime, plural, statusTone } from './goalStatus.js';
import styles from './GoalTransition.module.css';

const DIVIDERS = {
    started: { icon: 'bi-bullseye', tone: 'accent' },
    run: { icon: 'bi-play-circle', tone: 'accent' },
    resumed: { icon: 'bi-play-circle', tone: 'accent' },
    reopened: { icon: 'bi-arrow-repeat', tone: 'accent' },
    paused: statusTone('paused'),
    scheduled: statusTone('scheduled'),
    waiting: statusTone('waiting'),
    error: statusTone('error'),
    completed: statusTone('done'),
    cancelled: statusTone('cancelled'),
};

function dividerText(event) {
    switch (event.transition) {
    case 'started': return { label: 'Goal started', detail: event.objective };
    case 'run': return { label: 'Goal run', detail: event.step };
    case 'scheduled': return { label: `Resumes ${formatRunTime(event.resumeAt)}` };
    case 'waiting': return { label: 'Waiting for you', detail: event.questionCount ? plural(event.questionCount, 'question') : '' };
    case 'error': return { label: 'Stopped by an error' };
    case 'completed': return { label: 'Goal done' };
    case 'cancelled': return { label: 'Goal cancelled' };
    case 'reopened': return { label: 'Goal reopened' };
    case 'paused': return { label: 'Paused' };
    case 'resumed': return { label: 'Resumed' };
    default: return { label: 'Goal updated' };
    }
}

function formatTime(value) {
    return new Date(value).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

/** A one-line goal divider. Its time shows on hover; day headers carry the date. */
export default function GoalTransition({ event }) {
    const { icon, tone } = DIVIDERS[event.transition] || statusTone('waiting');
    const { label, detail } = dividerText(event);
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
