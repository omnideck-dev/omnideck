import ConfirmButton from './primitives/ConfirmButton.jsx';
import { label } from './conversationSections.js';
import styles from './ConversationArchivedSection.module.css';

/**
 * Collapsible footer listing archived conversations. Loaded up front so its
 * count shows on the collapsed header. Each row can be restored back into the
 * recents or permanently deleted; archived rows are read-only otherwise (open a
 * conversation by restoring it first).
 */
export default function ConversationArchivedSection({ open, loaded, items, deleting, onToggle, onRestore, onDelete }) {
    return (
        <div className={styles.archived} data-testid="archived-section">
            <button
                type="button"
                className={styles.archivedToggle}
                onClick={onToggle}
                aria-expanded={open}
                data-testid="archived-toggle"
            >
                <i className={`bi ${open ? 'bi-chevron-down' : 'bi-chevron-right'}`} />
                <i className="bi bi-archive" />
                <span>Archived</span>
                {loaded && items.length > 0 && (
                    <span className={styles.archivedCount}>{items.length}</span>
                )}
            </button>
            {open && (
                <div className={styles.archivedList}>
                    {loaded && items.length === 0 && (
                        <div className={styles.empty} data-testid="archived-empty">
                            No archived conversations
                        </div>
                    )}
                    {items.map((convo) => {
                        const id = convo.conversation_id;
                        return (
                            <div
                                key={id}
                                className={styles.archivedItem}
                                title={label(convo)}
                                data-testid="archived-item"
                                data-conversation-id={id}
                            >
                                <span className={styles.itemTitle}>{label(convo)}</span>
                                <button
                                    type="button"
                                    className={styles.archivedAction}
                                    onClick={() => onRestore(convo)}
                                    title="Restore conversation"
                                    aria-label="Restore conversation"
                                    data-testid="archived-restore"
                                >
                                    <i className="bi bi-arrow-counterclockwise" />
                                </button>
                                <ConfirmButton
                                    onConfirm={() => onDelete(id)}
                                    label=""
                                    confirmLabel="Confirm?"
                                    icon="bi-trash3"
                                    disabled={deleting === id}
                                    className={styles.archivedDelete}
                                    confirmClassName={styles.archivedDeleteArmed}
                                    title="Delete permanently"
                                    data-testid="archived-delete"
                                />
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
