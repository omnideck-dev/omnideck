import IconButton from './primitives/IconButton.jsx';
import styles from './QueueStrip.module.css';

export const QUEUE_TITLE = "Queued for the agent's next step";

/**
 * Messages waiting for the agent's next step, joined to the top edge of the
 * message box. Rows are `{id, label, editable}`. Clicking an editable row's
 * label calls `onEdit`; every row can be removed. Renders nothing when empty.
 */
export default function QueueStrip({ rows, onRemove, onEdit, disabled = false }) {
    if (!rows?.length) return null;
    return <section className={styles.strip} aria-label={QUEUE_TITLE} data-testid="queue-strip">
        <div className={styles.title}>{QUEUE_TITLE}</div>
        <ul className={styles.list}>
            {rows.map((row) => <li key={row.id} className={styles.row}>
                {row.editable
                    ? <button type="button" className={styles.textButton} title="Edit message"
                        disabled={disabled} onClick={() => onEdit?.(row.id)}>{row.label}</button>
                    : <span className={styles.text}>{row.label}</span>}
                <IconButton size="xs" aria-label="Remove queued message" title="Remove"
                    disabled={disabled} onClick={() => onRemove?.(row.id)}>
                    <i className="bi bi-x" aria-hidden="true" />
                </IconButton>
            </li>)}
        </ul>
    </section>;
}
