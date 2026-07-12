import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useConversations } from '../contexts/Conversations.jsx';
import ConfirmButton from './primitives/ConfirmButton.jsx';
import SearchInput from './primitives/SearchInput.jsx';
import styles from './ConversationsPanel.module.css';

const BUCKET_ORDER = ['Today', 'Yesterday', 'Earlier'];
const MAX_TITLE_LEN = 50;
const MAX_FOLDER_NAME_LEN = 40;
const MENU_WIDTH = 176;
const DEFAULT_FOLDER_ICON = 'bi-folder';
// Curated Bootstrap icons offered in the folder icon picker. Kept in sync with
// the server's icon-shape validation (any `bi-*` class is accepted there).
const FOLDER_ICONS = [
    'bi-folder', 'bi-briefcase', 'bi-code-slash', 'bi-book', 'bi-lightbulb',
    'bi-star', 'bi-heart', 'bi-flag', 'bi-bug', 'bi-rocket',
    'bi-music-note-beamed', 'bi-camera', 'bi-cpu', 'bi-gear', 'bi-graph-up-arrow',
    'bi-chat-dots', 'bi-journal-text', 'bi-kanban', 'bi-mortarboard', 'bi-controller',
    'bi-terminal', 'bi-box-seam', 'bi-tag', 'bi-house', 'bi-globe2',
    'bi-palette', 'bi-trophy', 'bi-basket',
];
// Persisted set of collapsed section keys. Keyed by stable section identity
// ('pinned', 'folder:<id>', 'Today'…) so a chat migrating between date buckets
// never carries a stale collapsed flag with it.
const COLLAPSE_KEY = 'omnideck_sidebar_collapsed_sections';

/** Bucket a conversation's start time into Today / Yesterday / Earlier. */
function _dayBucket(iso) {
    if (!iso) return 'Earlier';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'Earlier';
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startOfYesterday = new Date(startOfToday);
    startOfYesterday.setDate(startOfYesterday.getDate() - 1);
    if (d >= startOfToday) return 'Today';
    if (d >= startOfYesterday) return 'Yesterday';
    return 'Earlier';
}

function _label(convo) {
    return convo.title || convo.first_message || '(empty)';
}

/** A slim relative-age stamp (e.g. "3h", "2d") shown inline on search results. */
function _relativeAge(iso) {
    if (!iso) return '';
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return '';
    const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hrs = Math.round(mins / 60);
    if (hrs < 24) return `${hrs}h`;
    const days = Math.round(hrs / 24);
    if (days < 7) return `${days}d`;
    const weeks = Math.round(days / 7);
    if (weeks < 5) return `${weeks}w`;
    const months = Math.round(days / 30);
    if (months < 12) return `${months}mo`;
    return `${Math.round(days / 365)}y`;
}

/** The value the rename input opens with — the visible label, sans placeholder. */
function _renameSeed(convo) {
    return convo.title || convo.first_message || '';
}

function _loadCollapsed() {
    try {
        const raw = localStorage.getItem(COLLAPSE_KEY);
        return new Set(Array.isArray(JSON.parse(raw)) ? JSON.parse(raw) : []);
    } catch {
        return new Set();
    }
}

function _persistCollapsed(set) {
    try {
        localStorage.setItem(COLLAPSE_KEY, JSON.stringify([...set]));
    } catch {
        // localStorage unavailable — collapse still works for the session.
    }
}

/**
 * Split the conversation list into ordered, collapsible sections: Pinned first,
 * then each custom folder (in the folders' own order), then the Today /
 * Yesterday / Earlier date buckets for everything left unfiled. A pinned chat
 * shows only under Pinned; a foldered chat shows only under its folder; the
 * rest fall through to the date buckets. Folders stay visible even when empty
 * (so they can be managed), except while searching, where empty ones hide.
 */
function _buildSections(items, folders, folderById, query) {
    const q = query.trim().toLowerCase();
    const filtered = q
        ? items.filter((c) => _label(c).toLowerCase().includes(q))
        : items;

    const sections = [];

    const pinned = filtered.filter((c) => c.pinned);
    if (pinned.length) sections.push({ key: 'pinned', kind: 'pinned', label: 'Pinned', items: pinned });

    // Group the unpinned, filed conversations by folder.
    const byFolder = new Map();
    for (const c of filtered) {
        if (c.pinned) continue;
        const fid = c.folder_id && folderById.has(c.folder_id) ? c.folder_id : null;
        if (!fid) continue;
        if (!byFolder.has(fid)) byFolder.set(fid, []);
        byFolder.get(fid).push(c);
    }
    for (const folder of folders) {
        const folderItems = byFolder.get(folder.id) || [];
        if (q && folderItems.length === 0) continue;
        sections.push({ key: `folder:${folder.id}`, kind: 'folder', label: folder.name, folder, items: folderItems });
    }

    // Everything not pinned and not in a known folder keeps the date buckets.
    const byBucket = new Map();
    for (const c of filtered) {
        if (c.pinned) continue;
        if (c.folder_id && folderById.has(c.folder_id)) continue;
        const bucket = _dayBucket(c.started_at);
        if (!byBucket.has(bucket)) byBucket.set(bucket, []);
        byBucket.get(bucket).push(c);
    }
    for (const b of BUCKET_ORDER) {
        if (byBucket.has(b)) sections.push({ key: b, kind: 'date', label: b, items: byBucket.get(b) });
    }
    return sections;
}

/**
 * Inline list of recent conversations for the sidebar: a search box over a
 * grouped, scrollable list. Conversations group into Pinned, custom folders,
 * and Today / Yesterday / Earlier date buckets — every group a collapsible
 * section. A per-row 3-dot menu pins, renames, files-into-a-folder, archives,
 * or deletes; folder headers can be renamed or deleted.
 */
export default function ConversationsPanel({ onLoadConversation, onNewConversation, activeConversationId }) {
    const {
        items, setItems, loading, deleting, handleDelete,
        archiveConversation, unarchiveConversation,
        folders, createFolder, renameFolder, setFolderIcon, deleteFolder, setConversationFolder,
    } = useConversations();
    const [query, setQuery] = useState('');
    // Which row's context menu is open, plus the trigger rect to anchor it.
    const [menu, setMenu] = useState(null); // { id, rect } | null
    const [renamingId, setRenamingId] = useState(null);
    const [collapsed, setCollapsed] = useState(_loadCollapsed);
    const [creatingFolder, setCreatingFolder] = useState(false);
    const [renamingFolderId, setRenamingFolderId] = useState(null);
    // Which folder's icon picker is open, plus the trigger rect to anchor it.
    const [iconPicker, setIconPicker] = useState(null); // { folderId, rect } | null
    // Which folder's options menu is open, plus the trigger rect to anchor it.
    const [folderMenu, setFolderMenu] = useState(null); // { folderId, rect } | null
    // Archived conversations are loaded lazily the first time the section is
    // expanded, then kept current locally by restore/delete like the main list.
    const [showArchived, setShowArchived] = useState(false);
    const [archived, setArchived] = useState([]);
    const [archivedLoaded, setArchivedLoaded] = useState(false);

    const closeMenu = useCallback(() => setMenu(null), []);

    const openMenu = useCallback((id, rect) => {
        setMenu((cur) => (cur?.id === id ? null : { id, rect }));
    }, []);

    const folderById = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);

    const searching = query.trim().length > 0;

    // While searching we drop the section structure entirely and show a flat,
    // recency-sorted list of matches (each with an inline age). Sections are
    // only built when not searching.
    const searchResults = useMemo(() => {
        if (!searching) return [];
        const q = query.trim().toLowerCase();
        return items
            .filter((c) => _label(c).toLowerCase().includes(q))
            .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
    }, [items, query, searching]);

    const sections = useMemo(
        () => (searching ? [] : _buildSections(items, folders, folderById, query)),
        [items, folders, folderById, query, searching],
    );

    const hasRows = sections.some((s) => s.items.length > 0);

    const toggleSection = useCallback((key) => {
        setCollapsed((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            _persistCollapsed(next);
            return next;
        });
    }, []);

    const patchConversation = useCallback(async (id, body) => {
        try {
            await fetch(`/api/conversations/sessions/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
        } catch (_) {
            // The optimistic update already reflects the change; a failed
            // write surfaces on the next refetch rather than blocking the UI.
        }
    }, []);

    const togglePin = useCallback((convo) => {
        const pinned = !convo.pinned;
        setItems((prev) => prev.map((c) => (
            c.conversation_id === convo.conversation_id ? { ...c, pinned } : c
        )));
        closeMenu();
        patchConversation(convo.conversation_id, { pinned });
    }, [setItems, closeMenu, patchConversation]);

    const submitRename = useCallback((convo, raw) => {
        // Blank input reverts to the first-message fallback rather than saving
        // an empty title.
        const title = raw.trim().slice(0, MAX_TITLE_LEN);
        setRenamingId(null);
        setItems((prev) => prev.map((c) => (
            c.conversation_id === convo.conversation_id ? { ...c, title } : c
        )));
        patchConversation(convo.conversation_id, { title });
    }, [setItems, patchConversation]);

    const deleteConversation = useCallback(async (id) => {
        await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            (s) => s.conversation_id !== id,
        );
        closeMenu();
        // Deleting the open conversation leaves nothing selected — start fresh.
        if (id === activeConversationId) onNewConversation?.();
    }, [handleDelete, closeMenu, activeConversationId, onNewConversation]);

    const moveToFolder = useCallback((convo, folderId) => {
        setConversationFolder(convo.conversation_id, folderId);
        closeMenu();
    }, [setConversationFolder, closeMenu]);

    const archiveConvo = useCallback(async (convo) => {
        closeMenu();
        const id = convo.conversation_id;
        const removed = await archiveConversation(id);
        // Mirror it into the archived list if that section is already loaded,
        // so the count and rows stay current without a refetch.
        if (removed && archivedLoaded) {
            setArchived((prev) => (
                prev.some((c) => c.conversation_id === id) ? prev : [removed, ...prev]
            ));
        }
        // Archiving the open conversation leaves nothing selected — start fresh.
        if (id === activeConversationId) onNewConversation?.();
    }, [closeMenu, archiveConversation, archivedLoaded, activeConversationId, onNewConversation]);

    // Load the archived list up front so its count shows on the collapsed
    // header — you can see how many are archived without expanding.
    useEffect(() => {
        let cancelled = false;
        fetch('/api/conversations/archived')
            .then((r) => (r.ok ? r.json() : []))
            .then((data) => { if (!cancelled) { setArchived(data); setArchivedLoaded(true); } })
            .catch(() => { if (!cancelled) setArchivedLoaded(true); });
        return () => { cancelled = true; };
    }, []);

    const toggleArchived = useCallback(() => setShowArchived((cur) => !cur), []);

    const restoreArchived = useCallback((convo) => {
        const id = convo.conversation_id;
        setArchived((prev) => prev.filter((c) => c.conversation_id !== id));
        unarchiveConversation(convo);
    }, [unarchiveConversation]);

    const deleteArchived = useCallback(async (id) => {
        await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            () => true, // the active list doesn't hold archived rows; nothing to filter
        );
        setArchived((prev) => prev.filter((c) => c.conversation_id !== id));
    }, [handleDelete]);

    const submitNewFolder = useCallback((raw) => {
        setCreatingFolder(false);
        const name = raw.trim().slice(0, MAX_FOLDER_NAME_LEN);
        if (name) createFolder(name);
    }, [createFolder]);

    const submitRenameFolder = useCallback((folderId, raw) => {
        setRenamingFolderId(null);
        const name = raw.trim().slice(0, MAX_FOLDER_NAME_LEN);
        if (name) renameFolder(folderId, name);
    }, [renameFolder]);

    const openIconPicker = useCallback((folderId, rect) => {
        setIconPicker((cur) => (cur?.folderId === folderId ? null : { folderId, rect }));
    }, []);

    const pickIcon = useCallback((icon) => {
        setIconPicker((cur) => {
            if (cur) setFolderIcon(cur.folderId, icon);
            return null;
        });
    }, [setFolderIcon]);

    // Toggle so clicking the same folder's 3-dot closes an already-open menu.
    const toggleFolderMenu = useCallback((folderId, rect) => {
        setFolderMenu((cur) => (cur?.folderId === folderId ? null : { folderId, rect }));
    }, []);

    const menuConvo = menu ? items.find((c) => c.conversation_id === menu.id) : null;

    const renderRow = (convo, { showAge = false } = {}) => {
        const id = convo.conversation_id;
        if (renamingId === id) {
            return (
                <RenameRow
                    key={id}
                    convo={convo}
                    onSubmit={(raw) => submitRename(convo, raw)}
                    onCancel={() => setRenamingId(null)}
                />
            );
        }
        const active = id === activeConversationId;
        const menuOpen = menu?.id === id;
        return (
            <div
                key={id}
                className={[
                    styles.item,
                    active ? styles.active : '',
                    menuOpen ? styles.menuOpen : '',
                ].filter(Boolean).join(' ')}
                onClick={() => onLoadConversation(id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onLoadConversation(id);
                    }
                }}
                title={_label(convo)}
                data-testid="recent-item"
                data-conversation-id={id}
                data-pinned={convo.pinned ? 'true' : 'false'}
                data-folder-id={convo.folder_id || ''}
            >
                <span className={styles.itemTitle}>{_label(convo)}</span>
                {showAge && (
                    <span className={styles.itemAge} data-testid="recent-item-age">
                        {_relativeAge(convo.started_at)}
                    </span>
                )}
                <button
                    className={styles.menuBtn}
                    // Stop mousedown reaching the menu's outside-click handler so
                    // re-clicking an open menu's trigger toggles it shut.
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => {
                        e.stopPropagation();
                        openMenu(id, e.currentTarget.getBoundingClientRect());
                    }}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    title="Conversation options"
                    aria-label="Conversation options"
                    data-testid="recent-menu-trigger"
                >
                    <i className="bi bi-three-dots-vertical" />
                </button>
            </div>
        );
    };

    return (
        <div className={styles.recent} data-testid="recent-conversations">
            <div className={styles.searchRow}>
                <SearchInput
                    className={styles.search}
                    value={query}
                    onChange={setQuery}
                    placeholder="Search conversations…"
                    ariaLabel="Search conversations"
                    testId="recent-search"
                    clearTestId="recent-search-clear"
                />
                <button
                    type="button"
                    className={styles.newFolderBtn}
                    onClick={() => setCreatingFolder(true)}
                    title="New folder"
                    aria-label="New folder"
                    data-testid="recent-new-folder"
                >
                    <i className="bi bi-folder-plus" />
                </button>
            </div>

            <div className={styles.list}>
                {creatingFolder && (
                    <InlineNameInput
                        placeholder="Folder name"
                        onSubmit={submitNewFolder}
                        onCancel={() => setCreatingFolder(false)}
                        testId="recent-new-folder-input"
                    />
                )}

                {searching && searchResults.length === 0 && (
                    <div className={styles.empty} data-testid="recent-empty">
                        {`No matches for "${query}"`}
                    </div>
                )}
                {!searching && !loading && !hasRows && !creatingFolder && folders.length === 0 && (
                    <div className={styles.empty} data-testid="recent-empty">
                        No conversations yet
                    </div>
                )}

                {searching && searchResults.map((convo) => renderRow(convo, { showAge: true }))}

                {!searching && sections.map((section) => {
                    const isCollapsed = collapsed.has(section.key);
                    return (
                        <div key={section.key} data-testid="recent-section" data-section={section.key}>
                            {section.kind === 'folder' && renamingFolderId === section.folder.id ? (
                                <div className={styles.folderRename}>
                                    <i className={`bi ${section.folder.icon || DEFAULT_FOLDER_ICON} ${styles.folderGlyph}`} />
                                    <InlineNameInput
                                        seed={section.folder.name}
                                        placeholder="Folder name"
                                        onSubmit={(raw) => submitRenameFolder(section.folder.id, raw)}
                                        onCancel={() => setRenamingFolderId(null)}
                                        testId="recent-folder-rename-input"
                                        bare
                                    />
                                </div>
                            ) : (
                                <SectionHeader
                                    section={section}
                                    collapsed={isCollapsed}
                                    menuOpen={folderMenu?.folderId === section.folder?.id}
                                    onToggle={() => toggleSection(section.key)}
                                    onOpenFolderMenu={(rect) => toggleFolderMenu(section.folder.id, rect)}
                                />
                            )}
                            {!isCollapsed && section.items.map(renderRow)}
                        </div>
                    );
                })}
            </div>

            {menuConvo && (
                <ConversationMenu
                    convo={menuConvo}
                    rect={menu.rect}
                    folders={folders}
                    deleting={deleting === menuConvo.conversation_id}
                    onClose={closeMenu}
                    onTogglePin={() => togglePin(menuConvo)}
                    onRename={() => { setRenamingId(menuConvo.conversation_id); closeMenu(); }}
                    onMoveToFolder={(folderId) => moveToFolder(menuConvo, folderId)}
                    onArchive={() => archiveConvo(menuConvo)}
                    onDelete={() => deleteConversation(menuConvo.conversation_id)}
                />
            )}

            {folderMenu && (
                <FolderMenu
                    rect={folderMenu.rect}
                    onClose={() => setFolderMenu(null)}
                    onChangeIcon={() => { openIconPicker(folderMenu.folderId, folderMenu.rect); setFolderMenu(null); }}
                    onRename={() => { setRenamingFolderId(folderMenu.folderId); setFolderMenu(null); }}
                    onDelete={() => { deleteFolder(folderMenu.folderId); setFolderMenu(null); }}
                />
            )}

            {iconPicker && (
                <IconPicker
                    rect={iconPicker.rect}
                    current={folderById.get(iconPicker.folderId)?.icon}
                    onPick={pickIcon}
                    onClose={() => setIconPicker(null)}
                />
            )}

            <ArchivedSection
                open={showArchived}
                loaded={archivedLoaded}
                items={archived}
                deleting={deleting}
                onToggle={toggleArchived}
                onRestore={restoreArchived}
                onDelete={deleteArchived}
            />
        </div>
    );
}

/**
 * A collapsible section header. Pinned and date buckets show a label + count;
 * folder headers put the folder's icon inline (like the pin) and add a hover
 * 3-dot button that opens the folder menu. Clicking the label toggles the
 * section's collapsed state.
 */
function SectionHeader({ section, collapsed, menuOpen, onToggle, onOpenFolderMenu }) {
    const isFolder = section.kind === 'folder';
    return (
        <div className={[
            styles.dayLabel,
            isFolder ? styles.folderHead : '',
            menuOpen ? styles.menuOpen : '',
        ].filter(Boolean).join(' ')}>
            <button
                type="button"
                className={styles.sectionToggle}
                onClick={onToggle}
                aria-expanded={!collapsed}
                data-testid="recent-section-toggle"
            >
                <i className={`bi ${collapsed ? 'bi-chevron-right' : 'bi-chevron-down'} ${styles.chev}`} />
                {section.kind === 'pinned' && <i className="bi bi-pin-angle-fill" />}
                {isFolder && <i className={`bi ${section.folder.icon || DEFAULT_FOLDER_ICON} ${styles.folderInlineIcon}`} />}
                <span className={styles.sectionName}>{section.label}</span>
            </button>
            {/* Count and the folder ⋮ share the trailing slot: on folder hover /
                menu-open the count hides and the ⋮ takes its place, so counts
                stay aligned across every section and nothing is left empty. */}
            {section.items.length > 0 && <span className={styles.sectionCount}>{section.items.length}</span>}
            {isFolder && (
                <button
                    type="button"
                    className={styles.folderMenuBtn}
                    // Stop the mousedown from reaching the menu's outside-click
                    // handler, so clicking an open menu's trigger toggles it shut
                    // instead of closing-then-reopening.
                    onMouseDown={(e) => e.stopPropagation()}
                    onClick={(e) => { e.stopPropagation(); onOpenFolderMenu(e.currentTarget.getBoundingClientRect()); }}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen}
                    title="Folder options"
                    aria-label="Folder options"
                    data-testid="recent-folder-menu-trigger"
                >
                    <i className="bi bi-three-dots-vertical" />
                </button>
            )}
        </div>
    );
}

/**
 * The folder options menu, portaled to <body>. Collapses the folder's actions —
 * change icon, rename, delete — behind one 3-dot trigger so the header stays
 * uncluttered. Closes on outside click or Escape.
 */
function FolderMenu({ rect, onClose, onChangeIcon, onRename, onDelete }) {
    const ref = useRef(null);
    const [pos, setPos] = useState(null);

    useLayoutEffect(() => {
        const el = ref.current;
        const height = el ? el.offsetHeight : 0;
        const margin = 8;
        const left = Math.max(margin, rect.right - MENU_WIDTH);
        let top = rect.bottom + 4;
        if (top + height + margin > window.innerHeight) {
            top = Math.max(margin, rect.top - 4 - height);
        }
        setPos({ left, top });
    }, [rect]);

    useEffect(() => {
        const onDown = (e) => {
            if (ref.current?.contains(e.target)) return;
            onClose();
        };
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [onClose]);

    return createPortal(
        <div
            ref={ref}
            className={styles.menu}
            role="menu"
            data-testid="recent-folder-menu"
            style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
            onClick={(e) => e.stopPropagation()}
        >
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={onChangeIcon}
                data-testid="recent-folder-menu-icon"
            >
                <i className="bi bi-grid-3x3-gap" />
                Change icon
            </button>
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={onRename}
                data-testid="recent-folder-menu-rename"
            >
                <i className="bi bi-pencil" />
                Rename
            </button>
            <div className={styles.menuSep} />
            <ConfirmButton
                onConfirm={onDelete}
                label="Delete"
                confirmLabel="Confirm?"
                icon="bi-trash3"
                className={styles.menuDelete}
                confirmClassName={styles.menuDeleteArmed}
                data-testid="recent-folder-menu-delete"
            />
        </div>,
        document.body,
    );
}

/**
 * Collapsible footer listing archived conversations. Hidden behind a toggle
 * and loaded lazily on first open. Each row can be restored back into the
 * recents or permanently deleted; archived rows are read-only otherwise
 * (open a conversation by restoring it first).
 */
function ArchivedSection({ open, loaded, items, deleting, onToggle, onRestore, onDelete }) {
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
                                title={_label(convo)}
                                data-testid="archived-item"
                                data-conversation-id={id}
                            >
                                <span className={styles.itemTitle}>{_label(convo)}</span>
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

/**
 * The 3-dot context menu, portaled to <body> so the sidebar's overflow can't
 * clip it. Anchored under the trigger, right-aligned to it, flipping above
 * when there isn't room below. Closes on outside click or Escape. The "Move to
 * folder" item expands an inline picker of folders in place.
 */
function ConversationMenu({ convo, rect, folders, deleting, onClose, onTogglePin, onRename, onMoveToFolder, onArchive, onDelete }) {
    const ref = useRef(null);
    const [pos, setPos] = useState(null);
    const [pickerOpen, setPickerOpen] = useState(false);

    // Reposition on the picker toggle too — expanding it changes the menu
    // height, which can flip it above the trigger.
    useLayoutEffect(() => {
        const el = ref.current;
        const height = el ? el.offsetHeight : 0;
        const margin = 8;
        const left = Math.max(margin, rect.right - MENU_WIDTH);
        let top = rect.bottom + 4;
        if (top + height + margin > window.innerHeight) {
            top = Math.max(margin, rect.top - 4 - height);
        }
        setPos({ left, top });
    }, [rect, pickerOpen]);

    useEffect(() => {
        const onDown = (e) => {
            if (ref.current?.contains(e.target)) return;
            onClose();
        };
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [onClose]);

    return createPortal(
        <div
            ref={ref}
            className={styles.menu}
            role="menu"
            data-testid="recent-menu"
            style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
            onClick={(e) => e.stopPropagation()}
        >
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={onTogglePin}
                data-testid="recent-menu-pin"
            >
                <i className={`bi ${convo.pinned ? 'bi-pin-angle-fill' : 'bi-pin-angle'}`} />
                {convo.pinned ? 'Unpin' : 'Pin'}
            </button>
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={onRename}
                data-testid="recent-menu-rename"
            >
                <i className="bi bi-pencil" />
                Rename
            </button>
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={() => setPickerOpen((o) => !o)}
                aria-expanded={pickerOpen}
                data-testid="recent-menu-move"
            >
                <i className="bi bi-folder" />
                Move to folder
                <i className={`bi ${pickerOpen ? 'bi-chevron-down' : 'bi-chevron-right'} ${styles.menuCaret}`} />
            </button>
            {pickerOpen && (
                <div className={styles.folderPicker} data-testid="recent-menu-folders">
                    {folders.length === 0 && (
                        <div className={styles.folderPickerEmpty}>No folders yet</div>
                    )}
                    {folders.map((f) => (
                        <button
                            key={f.id}
                            type="button"
                            role="menuitem"
                            className={styles.menuItem}
                            onClick={() => onMoveToFolder(f.id)}
                            data-testid="recent-menu-folder-option"
                            data-folder-id={f.id}
                        >
                            <i className={`bi ${f.icon || DEFAULT_FOLDER_ICON}`} />
                            <span className={styles.folderPickerName}>{f.name}</span>
                            {convo.folder_id === f.id && <i className={`bi bi-check2 ${styles.folderCheck}`} />}
                        </button>
                    ))}
                    {convo.folder_id && (
                        <button
                            type="button"
                            role="menuitem"
                            className={styles.menuItem}
                            onClick={() => onMoveToFolder(null)}
                            data-testid="recent-menu-folder-remove"
                        >
                            <i className="bi bi-x-lg" />
                            Remove from folder
                        </button>
                    )}
                </div>
            )}
            <button
                type="button"
                role="menuitem"
                className={styles.menuItem}
                onClick={onArchive}
                data-testid="recent-menu-archive"
            >
                <i className="bi bi-archive" />
                Archive
            </button>
            <div className={styles.menuSep} />
            <ConfirmButton
                onConfirm={onDelete}
                label="Delete"
                confirmLabel="Confirm?"
                icon="bi-trash3"
                disabled={deleting}
                className={styles.menuDelete}
                confirmClassName={styles.menuDeleteArmed}
                data-testid="recent-menu-delete"
            />
        </div>,
        document.body,
    );
}

/**
 * Portaled grid of curated Bootstrap icons for choosing a folder's icon.
 * Anchored under the trigger, flipping above / clamping to the viewport when
 * there isn't room. Closes on outside click or Escape.
 */
function IconPicker({ rect, current, onPick, onClose }) {
    const ref = useRef(null);
    const [pos, setPos] = useState(null);

    useLayoutEffect(() => {
        const el = ref.current;
        const height = el ? el.offsetHeight : 0;
        const width = el ? el.offsetWidth : 220;
        const margin = 8;
        let left = rect.left;
        if (left + width + margin > window.innerWidth) {
            left = Math.max(margin, window.innerWidth - width - margin);
        }
        let top = rect.bottom + 4;
        if (top + height + margin > window.innerHeight) {
            top = Math.max(margin, rect.top - 4 - height);
        }
        setPos({ left, top });
    }, [rect]);

    useEffect(() => {
        const onDown = (e) => {
            if (ref.current?.contains(e.target)) return;
            onClose();
        };
        const onKey = (e) => { if (e.key === 'Escape') onClose(); };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [onClose]);

    return createPortal(
        <div
            ref={ref}
            className={styles.iconPicker}
            role="menu"
            data-testid="recent-icon-picker"
            style={pos ? { left: pos.left, top: pos.top } : { visibility: 'hidden' }}
            onClick={(e) => e.stopPropagation()}
        >
            {FOLDER_ICONS.map((icon) => (
                <button
                    key={icon}
                    type="button"
                    className={[styles.iconOption, icon === current ? styles.iconOptionActive : ''].filter(Boolean).join(' ')}
                    onClick={() => onPick(icon)}
                    title={icon.replace('bi-', '')}
                    aria-label={icon.replace('bi-', '')}
                    data-testid="recent-icon-option"
                    data-icon={icon}
                >
                    <i className={`bi ${icon}`} />
                </button>
            ))}
        </div>,
        document.body,
    );
}

/**
 * A small auto-focused text input for naming things inline (new folder, folder
 * rename). Enter submits, Escape cancels, blur cancels. A trailing blur after
 * an explicit commit is guarded so it doesn't double-fire.
 */
function InlineNameInput({ seed = '', placeholder, onSubmit, onCancel, testId, bare = false }) {
    const [value, setValue] = useState(seed);
    const inputRef = useRef(null);
    const doneRef = useRef(false);

    useEffect(() => {
        const el = inputRef.current;
        if (el) { el.focus(); el.select(); }
    }, []);

    const finish = (fn) => { doneRef.current = true; fn(); };

    return (
        <input
            ref={inputRef}
            className={bare ? styles.folderRenameInput : styles.newFolderInput}
            type="text"
            value={value}
            placeholder={placeholder}
            maxLength={MAX_FOLDER_NAME_LEN}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); finish(() => onSubmit(value)); }
                else if (e.key === 'Escape') { e.preventDefault(); finish(onCancel); }
            }}
            onBlur={() => { if (!doneRef.current) finish(() => onSubmit(value)); }}
            onClick={(e) => e.stopPropagation()}
            aria-label={placeholder}
            data-testid={testId}
        />
    );
}

/**
 * Edit-in-place rename row: an auto-focused input over the row, with Cancel
 * and Rename actions. Enter saves, Escape cancels, and blurring out of the
 * input reverts. The action buttons preventDefault on mousedown so clicking
 * them doesn't blur-cancel the input first.
 */
function RenameRow({ convo, onSubmit, onCancel }) {
    const seed = _renameSeed(convo);
    const [value, setValue] = useState(seed);
    const inputRef = useRef(null);
    // Once we've committed (save or explicit cancel), the input's unmount
    // fires a trailing blur — guard so it doesn't re-trigger a cancel.
    const doneRef = useRef(false);

    useEffect(() => {
        const el = inputRef.current;
        if (el) { el.focus(); el.select(); }
    }, []);

    const finish = (fn) => { doneRef.current = true; fn(); };
    const changed = value !== seed;

    return (
        <div className={styles.renameRow} data-testid="recent-rename">
            <input
                ref={inputRef}
                className={styles.renameInput}
                type="text"
                value={value}
                maxLength={MAX_TITLE_LEN}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter') { e.preventDefault(); finish(() => onSubmit(value)); }
                    else if (e.key === 'Escape') { e.preventDefault(); finish(onCancel); }
                }}
                onBlur={() => { if (!doneRef.current) finish(onCancel); }}
                aria-label="Rename conversation"
                data-testid="recent-rename-input"
            />
            <div className={styles.renameActions}>
                <button
                    type="button"
                    className={styles.renameCancel}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => finish(onCancel)}
                    data-testid="recent-rename-cancel"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    className={styles.renameSave}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => finish(() => onSubmit(value))}
                    disabled={!changed}
                    data-testid="recent-rename-save"
                >
                    Rename
                </button>
            </div>
        </div>
    );
}
