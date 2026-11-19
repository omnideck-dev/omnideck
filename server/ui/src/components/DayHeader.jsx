import styles from './DayHeader.module.css';

export function dayLabel(value) {
    const date = new Date(value);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return 'Today';
    if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return date.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
}

export default function DayHeader({ timestamp }) {
    return <div className={styles.day} data-testid="day-header" role="separator" aria-label={dayLabel(timestamp)}>
        <time dateTime={timestamp}>{dayLabel(timestamp)}</time>
    </div>;
}
