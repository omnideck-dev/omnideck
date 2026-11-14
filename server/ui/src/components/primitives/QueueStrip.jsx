import IconButton from './IconButton.jsx';
import styles from './QueueStrip.module.css';

export const QUEUE_TITLE = "Queued for the agent's next step";

/** Number of goal questions a queued message answers. */
export function answeredQuestionCount(message) {
    return (message.context || []).filter((item) => item?.type === 'goal_question').length;
}

function answersLabel(count) {
    return `Answers to ${count} ${count === 1 ? 'question' : 'questions'}`;
}

/**
 * Messages waiting for the agent's next step, shown above a composer.
 * Each row has a remove control. Clicking a text row's text calls `onEdit`;
 * answer rows only offer remove. Renders nothing for an empty queue.
 */
export default function QueueStrip({ messages, onRemove, onEdit, disabled = false }) {
    if (!messages?.length) return null;
    return <section className={styles.strip} aria-label={QUEUE_TITLE} data-testid="queue-strip">
        <div className={styles.title}>{QUEUE_TITLE}</div>
        <ul className={styles.list}>
            {messages.map((message) => {
                const answers = answeredQuestionCount(message);
                return <li key={message.id} className={styles.row}>
                    {answers > 0
                        ? <span className={styles.text}>{answersLabel(answers)}</span>
                        : <button type="button" className={styles.textButton} title="Edit message"
                            disabled={disabled} onClick={() => onEdit?.(message)}>{message.content}</button>}
                    <IconButton size="xs" aria-label="Remove queued message" title="Remove"
                        disabled={disabled} onClick={() => onRemove?.(message)}>
                        <i className="bi bi-x" aria-hidden="true" />
                    </IconButton>
                </li>;
            })}
        </ul>
    </section>;
}
