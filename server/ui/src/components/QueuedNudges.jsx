import { useState } from 'react';

import styles from './QueuedNudges.module.css';

export default function QueuedNudges({
    nudges = [],
    onDelete,
    disabled = false,
}) {
    const [expanded, setExpanded] = useState(true);
    const [deletingIds, setDeletingIds] = useState(() => new Set());

    if (nudges.length === 0) return null;

    const deleteNudge = async (nudge) => {
        if (!onDelete || disabled || deletingIds.has(nudge.id)) return;
        setDeletingIds((current) => new Set(current).add(nudge.id));
        try {
            await onDelete(nudge);
        } finally {
            setDeletingIds((current) => {
                const next = new Set(current);
                next.delete(nudge.id);
                return next;
            });
        }
    };

    return (
        <section className={styles.queue} data-testid="queued-nudges">
            <button
                type="button"
                className={styles.header}
                aria-expanded={expanded}
                onClick={() => setExpanded((current) => !current)}
            >
                <i
                    className={`bi ${expanded ? 'bi-chevron-down' : 'bi-chevron-right'} ${styles.chevron}`}
                    aria-hidden="true"
                />
                <span className={styles.title}>Queued nudges</span>
                <span className={styles.count}>{nudges.length}</span>
            </button>
            {expanded && (
                <ol className={styles.list}>
                    {nudges.map((nudge, index) => {
                        const deleting = deletingIds.has(nudge.id);
                        return (
                            <li className={styles.row} key={nudge.id}>
                                <span className={styles.index}>{index + 1}</span>
                                {index === 0 ? (
                                    <span className={styles.next}>NEXT</span>
                                ) : (
                                    <span aria-hidden="true" />
                                )}
                                <span className={styles.message} title={nudge.message}>
                                    {nudge.message}
                                </span>
                                <button
                                    type="button"
                                    className={styles.deleteButton}
                                    aria-label={`Delete queued nudge: ${nudge.message}`}
                                    title="Delete queued nudge"
                                    disabled={disabled || deleting}
                                    onClick={() => deleteNudge(nudge)}
                                >
                                    <i className={`bi ${deleting ? 'bi-hourglass-split' : 'bi-trash3'}`} />
                                </button>
                            </li>
                        );
                    })}
                </ol>
            )}
        </section>
    );
}
