import { useCallback, useEffect, useMemo, useState } from 'react';
import { useConversationCatalog } from '../features/conversation/catalog/ConversationCatalog.jsx';
import SearchInput from './primitives/SearchInput.jsx';
import SectionHeader from './ConversationSectionHeader.jsx';
import ArchivedSection from './ConversationArchivedSection.jsx';
import { ConversationMenu, FolderMenu, IconPicker } from './ConversationMenus.jsx';
import { InlineNameInput, RenameRow } from './ConversationInlineEditors.jsx';
import {
    MAX_TITLE_LEN,
    MAX_FOLDER_NAME_LEN,
    DEFAULT_FOLDER_ICON,
    label,
    relativeAge,
    loadCollapsed,
    persistCollapsed,
    buildSections,
} from './conversationSections.js';
import styles from './ConversationsPanel.module.css';

function pointRect(event) {
    return {
        left: event.clientX,
        right: event.clientX,
        top: event.clientY,
        bottom: event.clientY,
    };
}

/**
 * Inline list of recent conversations for the sidebar: a search box over a
 * grouped, scrollable list. Conversations group into Pinned, custom folders,
 * and Today / Yesterday / Earlier date buckets — every group a collapsible
 * section. A per-row 3-dot menu pins, renames, files-into-a-folder, archives,
 * or deletes; folder headers open a menu to change icon, rename, or delete.
 * Searching drops the structure and shows a flat, recency-sorted list.
 */
export default function ConversationsPanel({ onLoadConversation, onNewConversation, activeConversationId }) {
    const {
        items, setItems, loading, deleting, handleDelete,
        archiveConversation, unarchiveConversation,
        folders, createFolder, renameFolder, setFolderIcon, deleteFolder, setConversationFolder,
    } = useConversationCatalog();
    const [query, setQuery] = useState('');
    // Which row's context menu is open, plus the trigger rect to anchor it.
    const [menu, setMenu] = useState(null); // { id, rect } | null
    const [renamingId, setRenamingId] = useState(null);
    const [collapsed, setCollapsed] = useState(loadCollapsed);
    const [creatingFolder, setCreatingFolder] = useState(false);
    const [renamingFolderId, setRenamingFolderId] = useState(null);
    // Which folder's icon picker is open, plus the trigger rect to anchor it.
    const [iconPicker, setIconPicker] = useState(null); // { folderId, rect } | null
    // Which folder's options menu is open, plus the trigger rect to anchor it.
    const [folderMenu, setFolderMenu] = useState(null); // { folderId, rect } | null
    // Archived conversations load up front so their count shows on the
    // collapsed header; the list is kept current locally by archive/restore.
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
            .filter((c) => label(c).toLowerCase().includes(q))
            .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
    }, [items, query, searching]);

    const sections = useMemo(
        () => (searching ? [] : buildSections(items, folders, folderById, query)),
        [items, folders, folderById, query, searching],
    );

    const hasRows = sections.some((s) => s.items.length > 0);

    const toggleSection = useCallback((key) => {
        setCollapsed((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            persistCollapsed(next);
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
                onContextMenu={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    openMenu(id, pointRect(event));
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onLoadConversation(id);
                    }
                }}
                title={label(convo)}
                data-testid="recent-item"
                data-conversation-id={id}
                data-pinned={convo.pinned ? 'true' : 'false'}
                data-folder-id={convo.folder_id || ''}
            >
                <span className={styles.itemTitle}>{label(convo)}</span>
                {showAge && (
                    <span className={styles.itemAge} data-testid="recent-item-age">
                        {relativeAge(convo.started_at)}
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
            <div className={styles.sectionHeader}>
                <span>Conversations</span>
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

            <div className={styles.primary}>
                <button
                    type="button"
                    className={styles.newChat}
                    onClick={onNewConversation}
                    title="New chat"
                    aria-label="New chat"
                    data-testid="sidebar-new-chat"
                >
                    <span className={styles.newChatIcon}>
                        <i className="bi bi-plus-lg" />
                    </span>
                    <span>New chat</span>
                </button>
            </div>

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
