import { useCallback, useEffect, useMemo, useState } from 'react';
import { useConversationCatalog } from '../features/conversation/catalog/ConversationCatalog.jsx';
import { useToast } from './ToastProvider.jsx';
import { clearChatDraft } from '../utils/chatDraftStorage.js';
import StatusDot from './StatusDot.jsx';
import Spinner from './primitives/Spinner.jsx';
import IconButton from './primitives/IconButton.jsx';
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
import { goalNeedsAnswer, useGoals } from '../features/goals/GoalsState.jsx';
import GoalStatus from '../features/goals/GoalStatus.jsx';

const NEEDS_YOU = 'needs-you';

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
    const { enabled: goalsEnabled, goalsByConversation } = useGoals();
    const { addToast } = useToast();
    const {
        items, setItems, loading, deleting, handleDelete, activity,
        archiveConversation, unarchiveConversation,
        folders, createFolder, renameFolder, setFolderIcon, deleteFolder, setConversationFolder,
    } = useConversationCatalog();
    const [query, setQuery] = useState('');
    const [filterId, setFilterId] = useState(null);
    // The goal filter keeps chats that have a goal, finished or not.
    const filters = useMemo(() => [
        ...(goalsEnabled ? [{ id: 'goals', label: 'With a goal', chip: 'Goals', icon: 'bi-bullseye',
            match: (item) => Boolean(goalsByConversation[item.conversation_id]) }] : []),
        { id: 'running', label: 'Running now', chip: 'Running', icon: 'bi-arrow-repeat',
            match: (item) => activity.running.has(item.conversation_id) },
    ].map((f) => ({ ...f, count: items.filter(f.match).length })), [goalsEnabled, goalsByConversation, activity, items]);
    const activeFilter = filters.find((f) => f.id === filterId);
    const visibleItems = useMemo(
        () => (activeFilter ? items.filter(activeFilter.match) : items),
        [activeFilter, items],
    );
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
        return visibleItems
            .filter((c) => label(c).toLowerCase().includes(q))
            .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
    }, [visibleItems, query, searching]);

    const sections = useMemo(() => {
        if (searching) return [];
        const needsYou = goalsEnabled ? visibleItems.filter((item) => goalNeedsAnswer(goalsByConversation[item.conversation_id])) : [];
        const needsIds = new Set(needsYou.map((item) => item.conversation_id));
        const grouped = buildSections(visibleItems.filter((item) => !needsIds.has(item.conversation_id)), folders, folderById, query)
            // A filtered list leaves out folders with nothing that matches.
            .filter((section) => !activeFilter || section.items.length > 0);
        return needsYou.length ? [{ key: NEEDS_YOU, kind: 'goals', label: `Needs you · ${needsYou.length}`, items: needsYou }, ...grouped] : grouped;
    }, [visibleItems, folders, folderById, query, searching, goalsEnabled, goalsByConversation, activeFilter]);

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
        const result = await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            (s) => s.conversation_id !== id,
        );
        closeMenu();
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return;
        }
        clearChatDraft(id);
        // Deleting the open conversation leaves nothing selected — start fresh.
        if (id === activeConversationId) onNewConversation?.();
    }, [handleDelete, closeMenu, addToast, activeConversationId, onNewConversation]);

    const moveToFolder = useCallback((convo, folderId) => {
        setConversationFolder(convo.conversation_id, folderId);
        closeMenu();
    }, [setConversationFolder, closeMenu]);

    const archiveConvo = useCallback(async (convo) => {
        closeMenu();
        const id = convo.conversation_id;
        const result = await archiveConversation(convo);
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return;
        }
        // Mirror it into the archived list if that section is already loaded,
        // so the count and rows stay current without a refetch.
        if (archivedLoaded) {
            setArchived((prev) => (
                prev.some((c) => c.conversation_id === id) ? prev : [result.summary, ...prev]
            ));
        }
        // Archiving the open conversation leaves nothing selected — start fresh.
        if (id === activeConversationId) onNewConversation?.();
    }, [closeMenu, archiveConversation, addToast, archivedLoaded, activeConversationId, onNewConversation]);

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
        const result = await handleDelete(
            id,
            `/api/conversations/sessions/${id}`,
            () => true, // the active list doesn't hold archived rows; nothing to filter
        );
        if (!result.ok) {
            addToast(result.message, { type: result.status === 409 ? 'warn' : 'error' });
            return;
        }
        clearChatDraft(id);
        setArchived((prev) => prev.filter((c) => c.conversation_id !== id));
    }, [handleDelete, addToast]);

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
        const running = activity.running.has(id);
        const finished = activity.finished.has(id);
        const goal = goalsEnabled ? goalsByConversation[id] : null;
        return (
            <div
                key={id}
                className={[
                    styles.item,
                    goal ? styles.goalItem : '',
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
                {(running || finished) && (
                    <span
                        role="img"
                        aria-label={running ? 'Running' : 'Finished'}
                        title={running ? 'Running' : 'Finished'}
                        data-testid="conversation-activity"
                        data-status={running ? 'running' : 'finished'}
                    >
                        {running ? <Spinner /> : <StatusDot status="complete" />}
                    </span>
                )}
                <span className={styles.itemBody}>
                    <span className={styles.itemTitle}>{label(convo)}</span>
                    {goal && <GoalStatus goal={goal} compact />}
                </span>
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
                <IconButton
                    onClick={() => setCreatingFolder(true)}
                    title="New folder"
                    aria-label="New folder"
                    data-testid="recent-new-folder"
                >
                    <i className="bi bi-folder-plus" />
                </IconButton>
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
                    filters={filters}
                    filter={activeFilter?.id ?? null}
                    onFilterChange={setFilterId}
                    filterTestId="recent-filter"
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
                {!searching && !loading && !hasRows && !creatingFolder && (activeFilter || folders.length === 0) && (
                    <div className={styles.empty} data-testid="recent-empty">
                        {activeFilter ? 'No chats match this filter' : 'No conversations yet'}
                    </div>
                )}

                {searching && searchResults.map((convo) => renderRow(convo, { showAge: true }))}

                {!searching && sections.map((section) => {
                    // Needs you never collapses, so a new question is never hidden.
                    const isCollapsed = section.key !== NEEDS_YOU && collapsed.has(section.key);
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
                                    collapsible={section.key !== NEEDS_YOU}
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
