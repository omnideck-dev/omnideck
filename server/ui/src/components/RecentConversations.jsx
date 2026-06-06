import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import useListPanel from '../hooks/useListPanel.js';
import ConfirmButton from './primitives/ConfirmButton.jsx';
import SearchInput from './primitives/SearchInput.jsx';
import styles from './RecentConversations.module.css';

const BUCKET_ORDER = ['Today', 'Yesterday', 'Earlier'];
const MAX_TITLE_LEN = 50;
const MENU_WIDTH = 176;

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

/** The value the rename input opens with — the visible label, sans placeholder. */
function _renameSeed(convo) {
    return convo.title || convo.first_message || '';
}

/**
 * Inline list of recent conversations for the sidebar: a search box over a
 * day-grouped, scrollable list, with pinned conversations floated into their
 * own section at the top. Clicking a row loads that conversation; a per-row
 * 3-dot menu pins, renames, or deletes it.
 */
export default function RecentConversations({ onLoadConversation, onNewConversation, activeConversationId, refreshSignal = 0 }) {
    const { items, setItems, loading, deleting, handleDelete } = useListPanel(
        '/api/conversations/sessions',
        { getId: (s) => s.conversation_id, refreshSignal },
    );
    const [query, setQuery] = useState('');
    // Which row's context menu is open, plus the trigger rect to anchor it.
    const [menu, setMenu] = useState(null); // { id, rect } | null
    const [renamingId, setRenamingId] = useState(null);

    const closeMenu = useCallback(() => setMenu(null), []);

    const openMenu = useCallback((id, rect) => {
        setMenu((cur) => (cur?.id === id ? null : { id, rect }));
    }, []);

    const groups = useMemo(() => {
        const q = query.trim().toLowerCase();
        const filtered = q
            ? items.filter((c) => _label(c).toLowerCase().includes(q))
            : items;

        const result = [];
        const pinned = filtered.filter((c) => c.pinned);
        if (pinned.length) result.push({ bucket: 'Pinned', items: pinned });

        const byBucket = new Map();
        for (const convo of filtered) {
            if (convo.pinned) continue;
            const bucket = _dayBucket(convo.started_at);
            if (!byBucket.has(bucket)) byBucket.set(bucket, []);
            byBucket.get(bucket).push(convo);
        }
        for (const b of BUCKET_ORDER) {
            if (byBucket.has(b)) result.push({ bucket: b, items: byBucket.get(b) });
        }
        return result;
    }, [items, query]);

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

    const menuConvo = menu ? items.find((c) => c.conversation_id === menu.id) : null;

    return (
        <div className={styles.recent} data-testid="recent-conversations">
            <SearchInput
                className={styles.search}
                value={query}
                onChange={setQuery}
                placeholder="Search conversations…"
                ariaLabel="Search conversations"
                testId="recent-search"
                clearTestId="recent-search-clear"
            />

            <div className={styles.list}>
                {!loading && groups.length === 0 && (
                    <div className={styles.empty} data-testid="recent-empty">
                        {query ? `No matches for "${query}"` : 'No conversations yet'}
                    </div>
                )}
                {groups.map(({ bucket, items: convos }) => (
                    <div key={bucket}>
                        <div className={styles.dayLabel}>
                            {bucket === 'Pinned' && <i className="bi bi-pin-angle-fill" />}
                            {bucket}
                        </div>
                        {convos.map((convo) => {
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
                                >
                                    <span className={styles.itemTitle}>{_label(convo)}</span>
                                    <button
                                        className={styles.menuBtn}
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
                        })}
                    </div>
                ))}
            </div>

            {menuConvo && (
                <ConversationMenu
                    convo={menuConvo}
                    rect={menu.rect}
                    deleting={deleting === menuConvo.conversation_id}
                    onClose={closeMenu}
                    onTogglePin={() => togglePin(menuConvo)}
                    onRename={() => { setRenamingId(menuConvo.conversation_id); closeMenu(); }}
                    onDelete={() => deleteConversation(menuConvo.conversation_id)}
                />
            )}
        </div>
    );
}

/**
 * The 3-dot context menu, portaled to <body> so the sidebar's overflow can't
 * clip it. Anchored under the trigger, right-aligned to it, flipping above
 * when there isn't room below. Closes on outside click or Escape.
 */
function ConversationMenu({ convo, rect, deleting, onClose, onTogglePin, onRename, onDelete }) {
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
