import {
    useEffect,
    useMemo,
    useRef,
    useState,
} from 'react';

import useArtifacts from '../../hooks/useArtifacts.js';
import Badge from '../Badge.jsx';
import DeleteArtifactDialog from './DeleteArtifactDialog.jsx';
import Button from '../primitives/Button.jsx';
import IconButton from '../primitives/IconButton.jsx';
import SearchInput from '../primitives/SearchInput.jsx';
import Select from '../primitives/Select.jsx';
import SortableTable from '../primitives/SortableTable.jsx';
import { fileExt, timeAgo, typeIcon } from './_artifactUtils.js';
import styles from './ArtifactsHubView.module.css';

const SORTS = {
    name: { label: 'Name', defaultDir: 'asc', value: (a) => a.filename.toLowerCase() },
    created: { label: 'Created', defaultDir: 'desc', value: (a) => a.created_at },
    type: { label: 'Type', defaultDir: 'asc', value: (a) => fileExt(a.filename).toLowerCase() },
};

const PREVIEW_ROOT_MARGIN = '320px 0px';
const previewSubscriptions = new Map();
let sharedPreviewObserver = null;

function getPreviewObserver() {
    if (sharedPreviewObserver || !globalThis.IntersectionObserver) {
        return sharedPreviewObserver;
    }
    sharedPreviewObserver = new globalThis.IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            previewSubscriptions.get(entry.target)?.(entry.isIntersecting);
        });
    }, { rootMargin: PREVIEW_ROOT_MARGIN });
    return sharedPreviewObserver;
}

function observePreview(node, onChange) {
    const observer = getPreviewObserver();
    if (!observer) {
        // IntersectionObserver is unavailable in older/test environments.
        // Preserve the existing functional behavior in that fallback.
        onChange(true);
        return () => {};
    }
    previewSubscriptions.set(node, onChange);
    observer.observe(node);
    return () => {
        observer.unobserve(node);
        previewSubscriptions.delete(node);
        if (previewSubscriptions.size === 0) {
            observer.disconnect();
            sharedPreviewObserver = null;
        }
    };
}

function usePreviewViewport(visible) {
    const nodeRef = useRef(null);
    const [nearViewport, setNearViewport] = useState(false);
    useEffect(() => {
        if (!visible) {
            setNearViewport(false);
            return undefined;
        }
        if (!nodeRef.current) return undefined;
        return observePreview(nodeRef.current, setNearViewport);
    }, [visible]);
    return [nodeRef, visible && nearViewport];
}

function PreviewSkeleton({ kind, hidden, artifactId }) {
    const classes = [
        styles.previewSkeleton,
        hidden ? styles.previewSkeletonHidden : '',
    ].filter(Boolean).join(' ');
    if (kind === 'image') {
        return (
            <div
                className={`${classes} ${styles.imageSkeleton}`}
                data-testid={`artifact-preview-skeleton-${artifactId}`}
                data-hidden={hidden ? 'true' : 'false'}
                aria-hidden="true"
            />
        );
    }
    if (kind === 'text') {
        return (
            <div
                className={`${classes} ${styles.textSkeleton}`}
                data-testid={`artifact-preview-skeleton-${artifactId}`}
                data-hidden={hidden ? 'true' : 'false'}
                aria-hidden="true"
            >
                <i /><i /><i /><i /><i />
            </div>
        );
    }
    return (
        <div
            className={`${classes} ${styles.htmlSkeleton}`}
            data-testid={`artifact-preview-skeleton-${artifactId}`}
            data-hidden={hidden ? 'true' : 'false'}
            aria-hidden="true"
        >
            <div className={styles.htmlSkeletonTop}><i /><i /><i /></div>
            <div className={styles.htmlSkeletonBody}>
                <div className={styles.htmlSkeletonSide} />
                <div className={styles.htmlSkeletonMain}>
                    <i /><i /><i /><div />
                </div>
            </div>
        </div>
    );
}

function PreviewUnavailable() {
    return (
        <div className={styles.previewUnavailable}>
            <i className="bi bi-exclamation-circle" />
            <span>Preview unavailable</span>
        </div>
    );
}

function ImagePreview({ item }) {
    const [status, setStatus] = useState('loading');
    if (status === 'error') return <PreviewUnavailable />;
    return (
        <>
            <PreviewSkeleton
                kind="image"
                hidden={status === 'loaded'}
                artifactId={item.id}
            />
            <img
                className={`${styles.thumbImg} ${styles.previewAsset} ${
                    status === 'loaded' ? styles.previewAssetLoaded : ''
                }`}
                src={item.path}
                alt=""
                loading="lazy"
                onLoad={() => setStatus('loaded')}
                onError={() => setStatus('error')}
            />
        </>
    );
}

function HtmlPreview({ item }) {
    const [status, setStatus] = useState('loading');
    if (status === 'error') return <PreviewUnavailable />;
    return (
        <>
            <PreviewSkeleton
                kind="html"
                hidden={status === 'loaded'}
                artifactId={item.id}
            />
            <iframe
                className={`${styles.thumbFrame} ${styles.previewAsset} ${
                    status === 'loaded' ? styles.previewAssetLoaded : ''
                }`}
                src={item.path}
                title=""
                sandbox=""
                loading="lazy"
                tabIndex={-1}
                onLoad={() => setStatus('loaded')}
                onError={() => setStatus('error')}
            />
        </>
    );
}

function TextPreview({ item }) {
    const [status, setStatus] = useState('loading');
    const [text, setText] = useState('');
    useEffect(() => {
        const controller = new AbortController();
        fetch(item.path, { signal: controller.signal })
            .then((response) => {
                if (!response.ok) throw new Error('Preview request failed');
                return response.text();
            })
            .then((content) => {
                setText(content.slice(0, 1500));
                setStatus('loaded');
            })
            .catch((error) => {
                if (error.name !== 'AbortError') setStatus('error');
            });
        return () => controller.abort();
    }, [item.path]);

    if (status === 'error') return <PreviewUnavailable />;
    return (
        <>
            <PreviewSkeleton
                kind="text"
                hidden={status === 'loaded'}
                artifactId={item.id}
            />
            <pre className={`${styles.thumbText} ${styles.previewAsset} ${
                status === 'loaded' ? styles.previewAssetLoaded : ''
            }`}>{text}</pre>
        </>
    );
}

function MountedArtifactPreview({ item, kind }) {
    if (kind === 'image') return <ImagePreview item={item} />;
    if (kind === 'html') return <HtmlPreview item={item} />;
    if (kind === 'text') return <TextPreview item={item} />;
    return <i className={`bi ${typeIcon(item.content_type, item.filename)} ${styles.cardIcon}`} />;
}

// Cards and their metadata stay mounted. Only this preview surface responds to
// tab and viewport visibility, so inactive/offscreen iframes and fetches are
// released without discarding search, sort, or catalog state.
function ArtifactThumb({ item, visible }) {
    const { content_type: ct, path, filename } = item;
    const isImage = (ct || '').startsWith('image/') || /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(filename);
    const isHtml = ct === 'text/html' || /\.html?$/i.test(filename);
    const isPdf = ct === 'application/pdf' || /\.pdf$/i.test(filename);
    const isText = !isImage && !isHtml && !isPdf
        && ((ct || '').startsWith('text/') || /\.(md|markdown|csv|json|txt|ya?ml|log)$/i.test(filename));
    const kind = isImage ? 'image' : isHtml ? 'html' : isText ? 'text' : 'icon';
    const viewportManaged = kind !== 'icon';
    const [viewportRef, nearViewport] = usePreviewViewport(
        visible && viewportManaged,
    );
    const shouldMount = viewportManaged ? nearViewport : visible;

    return (
        <div
            ref={viewportRef}
            className={styles.thumbViewport}
            data-testid={`artifact-preview-${item.id}`}
        >
            {shouldMount && (
                <MountedArtifactPreview key={path} item={item} kind={kind} />
            )}
        </div>
    );
}

/**
 * Artifact library view, optionally scoped to one conversation, with grid
 * and table layouts, search, sorting, deletion, and missing-file cleanup.
 *
 * Selecting a present artifact asks the desktop to open an independent file
 * view. The library itself does not own a second preview presentation.
 */
export default function ArtifactsHubView({
    conversationId = null,
    onOpenArtifact,
    onClearConversationFilter,
    visible: viewVisible = true,
}) {
    const { items, loading, removeArtifact, pruneMissing } = useArtifacts({
        conversationId,
    });
    const [layout, setLayout] = useState('grid'); // 'grid' | 'table'
    const [query, setQuery] = useState('');
    const [sort, setSort] = useState({ key: 'created', dir: 'desc' });
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
    function sortBy(key) {
        setSort((s) => (s.key === key
            ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
            : { key, dir: SORTS[key].defaultDir }));
    }

    function requestDelete(artifact) {
        if (artifact.status === 'missing') {
            removeArtifact(artifact.id);
            return;
        }
        setPendingDelete(artifact);
    }

    function confirmDelete({ deleteFile }) {
        removeArtifact(pendingDelete.id, { deleteFile });
        setPendingDelete(null);
    }

    return (
        <div
            className={styles.view}
            data-testid="artifacts-hub"
            data-conversation-id={conversationId || ''}
        >
            <div className={styles.content}>
                <div className={styles.listPane}>
                    <div className={styles.listToolbar}>
                        <h1 className={styles.title}>
                            <i className="bi bi-collection" />
                            {conversationId ? 'Conversation artifacts' : 'Artifacts'}
                            <span className={styles.count}>{loading ? '' : `· ${visible.length}`}</span>
                        </h1>
                        {conversationId && (
                            <Button
                                variant="ghost"
                                className={styles.filter}
                                onClick={onClearConversationFilter}
                                title="Clear the conversation filter"
                                data-testid="artifacts-clear-conversation-filter"
                            >
                                <i className="bi bi-funnel-fill" />
                                This chat
                                <i className="bi bi-x-lg" aria-hidden="true" />
                            </Button>
                        )}
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
                        <div className={styles.sortCtl}>
                            <span>Sort</span>
                            <Select
                                className={styles.select}
                                value={sort.key}
                                onChange={(key) => setSort({ key, dir: SORTS[key].defaultDir })}
                                ariaLabel="Sort by"
                                testId="sort-key"
                                options={Object.entries(SORTS).map(([key, { label }]) => ({ value: key, label }))}
                            />
                            <IconButton
                                onClick={() => setSort((s) => ({ ...s, dir: s.dir === 'asc' ? 'desc' : 'asc' }))}
                                title={sort.dir === 'asc' ? 'Ascending' : 'Descending'}
                                aria-label="Toggle sort direction"
                                data-testid="sort-dir"
                            >
                                <i className={`bi ${sort.dir === 'asc' ? 'bi-sort-down-alt' : 'bi-sort-down'}`} />
                            </IconButton>
                        </div>
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
                                    className={`${styles.card} ${a.status === 'missing' ? styles.missing : ''}`}
                                    onClick={() => {
                                        if (a.status !== 'missing') onOpenArtifact?.(a);
                                    }}
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
                                        <ArtifactThumb item={a} visible={viewVisible} />
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
                        <SortableTable
                            rows={visible}
                            rowKey={(a) => a.id}
                            sort={sort}
                            onSort={sortBy}
                            onRowClick={(a) => {
                                if (a.status !== 'missing') onOpenArtifact?.(a);
                            }}
                            rowClassName={(a) => (a.status === 'missing' ? styles.missing : '')}
                            rowTestId="artifact-row"
                            testId="artifacts-table"
                            columns={[
                                { key: 'name', header: 'Name', sortable: true, render: (a) => (
                                    <span className={styles.tname}>
                                        <i className={`bi ${typeIcon(a.content_type, a.filename)}`} />
                                        {a.filename}
                                        {a.status === 'missing' && <Badge variant="warning">missing</Badge>}
                                    </span>
                                ) },
                                { key: 'type', header: 'Type', sortable: true, render: (a) => <Badge>{fileExt(a.filename) || 'file'}</Badge> },
                                { key: 'conversation', header: 'Conversation', cellClassName: styles.tconv, render: (a) => (
                                    <span title={a.conversation_title || 'Conversation deleted'}>
                                        {a.conversation_title || <span className={styles.muted}>deleted</span>}
                                    </span>
                                ) },
                                { key: 'created', header: 'Created', sortable: true, cellClassName: styles.when, render: (a) => (
                                    <span title={a.created_at}>{timeAgo(a.created_at)}</span>
                                ) },
                                { key: 'actions', header: '', cellClassName: styles.acts, revealOnHover: true, render: (a) => (
                                    <IconButton
                                        title="Delete artifact"
                                        aria-label="Delete artifact"
                                        onClick={(e) => { e.stopPropagation(); requestDelete(a); }}
                                        data-testid="artifact-delete"
                                    >
                                        <i className="bi bi-trash" />
                                    </IconButton>
                                ) },
                            ]}
                        />
                    )}
                    </div>
                </div>

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
