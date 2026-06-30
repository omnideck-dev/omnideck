import { useEffect, useMemo, useState } from 'react';

import useArtifacts from '../../hooks/useArtifacts.js';
import Badge from '../Badge.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import DeleteArtifactDialog from './DeleteArtifactDialog.jsx';
import { timeAgo, typeIcon } from './_artifactUtils.js';
import styles from './ArtifactsDrawer.module.css';

/**
 * In-conversation artifacts: a right-edge slide-over opened from the chat title
 * bar. Defaults to the current conversation's files with a toggle to show all.
 * Selecting a file opens it in the existing preview (via onPreview) and closes
 * the drawer. Delete reuses the shared dialog: a missing file is dropped without
 * a prompt, a present one confirms (with the option to unlink it).
 */
export default function ArtifactsDrawer({ conversationId, onPreview, onClose }) {
    const [showAll, setShowAll] = useState(false);
    const [query, setQuery] = useState('');
    const [pendingDelete, setPendingDelete] = useState(null);

    const { items, removeArtifact, pruneMissing } = useArtifacts({
        conversationId: showAll ? null : conversationId,
    });

    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        return q
            ? items.filter((a) => a.filename.toLowerCase().includes(q)
                || (a.path || '').toLowerCase().includes(q))
            : items;
    }, [items, query]);

    const missingCount = useMemo(
        () => items.filter((a) => a.status === 'missing').length, [items],
    );

    // Esc closes the drawer.
    useEffect(() => {
        function onKey(e) {
            if (e.key === 'Escape') onClose?.();
        }
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [onClose]);

    function openFile(a) {
        if (a.status === 'missing') return;
        onPreview?.({ filename: a.filename, content_type: a.content_type, path: a.path });
        onClose?.();
    }

    function requestDelete(a) {
        if (a.status === 'missing') {
            removeArtifact(a.id);
            return;
        }
        setPendingDelete(a);
    }

    function confirmDelete({ deleteFile }) {
        removeArtifact(pendingDelete.id, { deleteFile });
        setPendingDelete(null);
    }

    return (
        <div
            className={styles.scrim}
            onClick={(e) => { if (e.target === e.currentTarget) onClose?.(); }}
        >
            <aside className={styles.panel} data-testid="artifacts-drawer">
                <div className={styles.header}>
                    <span className={styles.title}><i className="bi bi-collection" /> Artifacts</span>
                    <div className={styles.seg} role="tablist" aria-label="Artifacts scope">
                        <button
                            className={!showAll ? styles.segOn : ''}
                            onClick={() => setShowAll(false)}
                            data-testid="drawer-scope-this"
                        >
                            This chat
                        </button>
                        <button
                            className={showAll ? styles.segOn : ''}
                            onClick={() => setShowAll(true)}
                            data-testid="drawer-scope-all"
                        >
                            All
                        </button>
                    </div>
                    <IconButton
                        title="Close"
                        aria-label="Close artifacts"
                        onClick={onClose}
                        data-testid="drawer-close"
                    >
                        <i className="bi bi-x-lg" />
                    </IconButton>
                </div>

                <div className={styles.toolbar}>
                    <SearchInput
                        className={styles.search}
                        value={query}
                        onChange={setQuery}
                        placeholder="Search artifacts…"
                        ariaLabel="Search artifacts"
                        testId="drawer-search"
                    />
                    {missingCount > 0 && (
                        <Button
                            variant="ghost"
                            onClick={pruneMissing}
                            title={`Remove ${missingCount} artifact${missingCount > 1 ? 's' : ''} whose file is no longer on disk`}
                            data-testid="drawer-prune-missing"
                        >
                            <i className="bi bi-trash3" /> Clear {missingCount}
                        </Button>
                    )}
                </div>

                <div className={styles.list}>
                    {visible.length === 0 ? (
                        <div className={styles.empty} data-testid="drawer-empty">
                            <i className="bi bi-collection" />
                            <div>{items.length === 0 ? 'No artifacts yet.' : 'No artifacts match your search.'}</div>
                        </div>
                    ) : visible.map((a) => (
                        <div
                            key={a.id}
                            className={`${styles.row} ${a.status === 'missing' ? styles.missing : ''}`}
                            onClick={() => openFile(a)}
                            data-testid="artifact-drawer-row"
                        >
                            <i className={`bi ${typeIcon(a.content_type, a.filename)} ${styles.rowIcon}`} />
                            <div className={styles.rowMain}>
                                <div className={styles.rowName} title={a.filename}>{a.filename}</div>
                                <div className={styles.rowSub}>
                                    {showAll && a.conversation_title && (
                                        <span className={styles.rowConv} title={a.conversation_title}>
                                            <i className="bi bi-chat-left-text" /> {a.conversation_title}
                                        </span>
                                    )}
                                    {a.status === 'missing'
                                        ? <Badge variant="warning">missing</Badge>
                                        : <span className={styles.when}>{timeAgo(a.created_at)}</span>}
                                </div>
                            </div>
                            <IconButton
                                className={styles.rowDel}
                                title="Delete artifact"
                                aria-label="Delete artifact"
                                onClick={(e) => { e.stopPropagation(); requestDelete(a); }}
                                data-testid="artifact-delete"
                            >
                                <i className="bi bi-trash" />
                            </IconButton>
                        </div>
                    ))}
                </div>
            </aside>

            {pendingDelete && (
                <DeleteArtifactDialog
                    artifact={pendingDelete}
                    onCancel={() => setPendingDelete(null)}
                    onConfirm={confirmDelete}
                />
            )}
        </div>
    );
}
