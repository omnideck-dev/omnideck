import { useEffect, useMemo, useState } from 'react';

import useArtifacts from '../../hooks/useArtifacts.js';
import Badge from '../Badge.jsx';
import DeleteArtifactDialog from './DeleteArtifactDialog.jsx';
import FilePreview from '../FilePreview.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import { fileExt, timeAgo, typeIcon } from './_artifactUtils.js';
import styles from './ArtifactsHubView.module.css';

const SORTS = {
    name: { label: 'Name', defaultDir: 'asc', value: (a) => a.filename.toLowerCase() },
    created: { label: 'Created', defaultDir: 'desc', value: (a) => a.created_at },
    type: { label: 'Type', defaultDir: 'asc', value: (a) => fileExt(a.filename).toLowerCase() },
};

// Lightweight per-card thumbnail. Images/HTML load lazily via the browser;
// text/markdown fetches its content once (no polling). Anything else (pdf,
// unknown) falls back to the type icon. This is the "heavy, droppable" grid
// path — if it ever costs too much, the grid toggle can be removed wholesale.
function ArtifactThumb({ item }) {
    const { content_type: ct, path, filename } = item;
    const isImage = (ct || '').startsWith('image/') || /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(filename);
    const isHtml = ct === 'text/html' || /\.html?$/i.test(filename);
    const isPdf = ct === 'application/pdf' || /\.pdf$/i.test(filename);
    const isText = !isImage && !isHtml && !isPdf
        && ((ct || '').startsWith('text/') || /\.(md|markdown|csv|json|txt|ya?ml|log)$/i.test(filename));

    const [text, setText] = useState('');
    useEffect(() => {
        if (!isText) return undefined;
        let cancelled = false;
        fetch(path)
            .then((r) => (r.ok ? r.text() : ''))
            .then((t) => { if (!cancelled) setText(t.slice(0, 1500)); })
            .catch(() => {});
        return () => { cancelled = true; };
    }, [isText, path]);

    if (isImage) return <img className={styles.thumbImg} src={path} alt="" loading="lazy" />;
    if (isHtml) {
        return (
            <iframe
                className={styles.thumbFrame}
                src={path}
                title=""
                sandbox=""
                loading="lazy"
                tabIndex={-1}
            />
        );
    }
    if (isText) return <pre className={styles.thumbText}>{text}</pre>;
    return <i className={`bi ${typeIcon(ct, filename)} ${styles.cardIcon}`} />;
}

/**
 * Global artifacts hub: every artifact across all conversations, in a grid or
 * table, with search, sort (name/created/type), an in-place preview pane
 * (reusing FilePreview), delete, and a prune-missing action.
 *
 * Each artifact carries its source conversation's title from the API
 * (`conversation_title`, null when that conversation is gone). When an
 * `onOpenConversation(artifact)` handler is supplied, the preview also offers an
 * "open in conversation" action; without it the hub still works (no open action).
 */
export default function ArtifactsHubView({ onOpenConversation }) {
    const { items, loading, removeArtifact, pruneMissing } = useArtifacts();
    const [layout, setLayout] = useState('grid'); // 'grid' | 'table'
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'created', dir: 'desc' });
    const [selected, setSelected] = useState(null);
    const [pendingDelete, setPendingDelete] = useState(null);

    const visible = useMemo(() => {
        const q = query.trim().toLowerCase();
        const matched = q
            ? items.filter((a) => a.filename.toLowerCase().includes(q)
                || (a.path || '').toLowerCase().includes(q))
            : items;
        const value = SORTS[sort.key].value;
        const dir = sort.dir === 'asc' ? 1 : -1;
        return [...matched].sort((a, b) => {
            const av = value(a);
            const bv = value(b);
            if (av < bv) return -dir;
            if (av > bv) return dir;
            return a.filename.localeCompare(b.filename);
        });
    }, [items, query, sort]);

    const missingCount = useMemo(
        () => items.filter((a) => a.status === 'missing').length, [items],
    );
    const activeSelected = selected && visible.some((a) => a.id === selected.id) ? selected : null;

    function sortBy(key) {
        setSort((s) => (s.key === key
            ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
            : { key, dir: SORTS[key].defaultDir }));
    }

    function requestDelete(artifact) {
        if (artifact.status === 'missing') {
            removeArtifact(artifact.id);
            if (selected?.id === artifact.id) setSelected(null);
            return;
        }
        setPendingDelete(artifact);
    }

    function confirmDelete({ deleteFile }) {
        removeArtifact(pendingDelete.id, { deleteFile });
        if (selected?.id === pendingDelete.id) setSelected(null);
        setPendingDelete(null);
    }

    const sortCaret = (key) => (sort.key === key
        ? <i className={`bi ${sort.dir === 'asc' ? 'bi-caret-up-fill' : 'bi-caret-down-fill'} ${styles.caret}`} />
        : null);

    return (
        <div className={styles.view} data-testid="artifacts-hub">
            <div className={styles.content}>
                <div className={styles.listPane}>
                    <div className={styles.listToolbar}>
                        <h1 className={styles.title}>
                            <i className="bi bi-collection" /> Artifacts
                            <span className={styles.count}>{loading ? '' : `· ${visible.length}`}</span>
                        </h1>
                        <SearchInput
                            className={styles.search}
                            value={query}
                            onChange={setQuery}
                            placeholder="Search artifacts…"
                            ariaLabel="Search artifacts"
                            testId="artifacts-search"
                        />
                        {missingCount > 0 && (
                            <Button
                                variant="ghost"
                                onClick={pruneMissing}
                                title={`Remove ${missingCount} artifact${missingCount > 1 ? 's' : ''} whose file is no longer on disk`}
                                data-testid="prune-missing"
                            >
                                <i className="bi bi-trash3" /> Clear {missingCount} missing
                            </Button>
                        )}
                        <label className={styles.sortCtl}>
                            <span>Sort</span>
                            <select
                                className={styles.select}
                                value={sort.key}
                                onChange={(e) => setSort({ key: e.target.value, dir: SORTS[e.target.value].defaultDir })}
                                aria-label="Sort by"
                                data-testid="sort-key"
                            >
                                {Object.entries(SORTS).map(([key, { label }]) => (
                                    <option key={key} value={key}>{label}</option>
                                ))}
                            </select>
                            <IconButton
                                onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
                                title={sort.dir === 'asc' ? 'Ascending' : 'Descending'}
                                aria-label="Toggle sort direction"
                                data-testid="sort-dir"
                            >
                                <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                            </IconButton>
                        </label>
                        <div className={styles.seg} role="tablist" aria-label="Layout">
                            <button
                                className={layout === 'grid' ? styles.segOn : ''}
                                onClick={() => setLayout('grid')}
                                title="Grid" aria-label="Grid view" data-testid="layout-grid"
                            >
                                <i className="bi bi-grid-3x3-gap" />
                            </button>
                            <button
                                className={layout === 'table' ? styles.segOn : ''}
                                onClick={() => setLayout('table')}
                                title="Table" aria-label="Table view" data-testid="layout-table"
                            >
                                <i className="bi bi-list-ul" />
                            </button>
                        </div>
                    </div>
                    <div className={styles.scroll}>
                    {!loading && visible.length === 0 && (
                        <div className={styles.empty} data-testid="artifacts-empty">
                            <i className="bi bi-collection" />
                            <div>{items.length === 0 ? 'No artifacts yet.' : 'No artifacts match your search.'}</div>
                        </div>
                    )}

                    {layout === 'grid' && visible.length > 0 && (
                        <div className={styles.grid}>
                            {visible.map((a) => (
                                <div
                                    key={a.id}
                                    className={`${styles.card} ${a.status === 'missing' ? styles.missing : ''} ${activeSelected?.id === a.id ? styles.sel : ''}`}
                                    onClick={() => setSelected(a)}
                                    data-testid="artifact-card"
                                >
                                    <IconButton
                                        className={styles.del}
                                        title="Delete artifact"
                                        aria-label="Delete artifact"
                                        onClick={(e) => { e.stopPropagation(); requestDelete(a); }}
                                        data-testid="artifact-delete"
                                    >
                                        <i className="bi bi-trash" />
                                    </IconButton>
                                    <div className={styles.cardTop}>
                                        <ArtifactThumb item={a} />
                                    </div>
                                    <div className={styles.cardMeta}>
                                        <div className={styles.cardName} title={a.filename}>{a.filename}</div>
                                        <div className={styles.cardRow}>
                                            <Badge>{fileExt(a.filename) || 'file'}</Badge>
                                            {a.status === 'missing'
                                                ? <Badge variant="warning">missing</Badge>
                                                : <span className={styles.when}>{timeAgo(a.created_at)}</span>}
                                        </div>
                                        <div className={styles.cardConv} title={a.conversation_title || 'Conversation deleted'}>
                                            <i className="bi bi-chat-left-text" />
                                            {a.conversation_title || 'Conversation deleted'}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}

                    {layout === 'table' && visible.length > 0 && (
                        <table className={styles.table}>
                            <thead>
                                <tr>
                                    <th className={styles.sortable} onClick={() => sortBy('name')}>Name {sortCaret('name')}</th>
                                    <th className={styles.sortable} onClick={() => sortBy('type')}>Type {sortCaret('type')}</th>
                                    <th>Conversation</th>
                                    <th className={styles.sortable} onClick={() => sortBy('created')}>Created {sortCaret('created')}</th>
                                    <th />
                                </tr>
                            </thead>
                            <tbody>
                                {visible.map((a) => (
                                    <tr
                                        key={a.id}
                                        className={`${a.status === 'missing' ? styles.missing : ''} ${activeSelected?.id === a.id ? styles.sel : ''}`}
                                        onClick={() => setSelected(a)}
                                        data-testid="artifact-row"
                                    >
                                        <td>
                                            <span className={styles.tname}>
                                                <i className={`bi ${typeIcon(a.content_type, a.filename)}`} />
                                                {a.filename}
                                                {a.status === 'missing' && <Badge variant="warning">missing</Badge>}
                                            </span>
                                        </td>
                                        <td><Badge>{fileExt(a.filename) || 'file'}</Badge></td>
                                        <td className={styles.tconv} title={a.conversation_title || 'Conversation deleted'}>
                                            {a.conversation_title || <span className={styles.muted}>deleted</span>}
                                        </td>
                                        <td className={styles.when} title={a.created_at}>{timeAgo(a.created_at)}</td>
                                        <td className={styles.acts}>
                                            <IconButton
                                                title="Delete artifact"
                                                aria-label="Delete artifact"
                                                onClick={(e) => { e.stopPropagation(); requestDelete(a); }}
                                                data-testid="artifact-delete"
                                            >
                                                <i className="bi bi-trash" />
                                            </IconButton>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                    </div>
                </div>

                {activeSelected && (
                    <aside className={styles.preview} data-testid="artifact-preview">
                        <div className={styles.previewHead}>
                            <span className={styles.previewLabel}>Preview</span>
                            {onOpenConversation && (
                                <Button
                                    variant="ghost"
                                    onClick={() => onOpenConversation(activeSelected)}
                                    disabled={!activeSelected.conversation_title}
                                    title={activeSelected.conversation_title
                                        ? 'Open the conversation that produced this file'
                                        : 'That conversation no longer exists'}
                                    data-testid="artifact-open-conversation"
                                >
                                    <i className="bi bi-box-arrow-up-right" /> Open in conversation
                                </Button>
                            )}
                            <IconButton
                                title="Close preview"
                                aria-label="Close preview"
                                onClick={() => setSelected(null)}
                                data-testid="preview-close"
                            >
                                <i className="bi bi-x-lg" />
                            </IconButton>
                        </div>
                        <div className={styles.previewBody}>
                            {activeSelected.status === 'missing' ? (
                                <div className={styles.empty}>
                                    <i className="bi bi-exclamation-triangle" />
                                    <div>This file no longer exists on disk.</div>
                                </div>
                            ) : (
                                <FilePreview item={activeSelected} />
                            )}
                        </div>
                    </aside>
                )}
            </div>

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
