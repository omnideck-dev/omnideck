import { useCallback, useMemo, useState } from 'react';

import ArchivedSection from '../../components/ConversationArchivedSection.jsx';
import { RenameRow } from '../../components/ConversationInlineEditors.jsx';
import { ConversationMenu } from '../../components/ConversationMenus.jsx';
import SectionHeader from '../../components/ConversationSectionHeader.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import SearchInput from '../../components/primitives/SearchInput.jsx';
import {
    buildSections,
    label,
    loadCollapsed,
    persistCollapsed,
} from '../../components/conversationSections.js';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import useConversationListActions from '../conversation/catalog/useConversationListActions.js';
import { useNeedsYou } from '../goals/conversationGoals.js';
import PhoneConversationRow from './PhoneConversationRow.jsx';
import styles from './PhoneConversationList.module.css';

const NEEDS_YOU = 'needs-you';

export default function PhoneConversationList({ activeConversationId, onOpenConversation, onStartChat, onResetConversation, onOpenArtifacts }) {
    const { items, loading, deleting, activity, folders } = useConversationCatalog();
    const actions = useConversationListActions({ activeConversationId, onNewConversation: onResetConversation });
    const needsYou = useNeedsYou(items);
    const [query, setQuery] = useState('');
    const [collapsed, setCollapsed] = useState(loadCollapsed);
    const [menu, setMenu] = useState(null);
    const [renamingId, setRenamingId] = useState(null);
    const [swipe, setSwipe] = useState(null);
    const [showArchived, setShowArchived] = useState(false);

    const folderById = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
    const searching = query.trim().length > 0;

    const searchResults = useMemo(() => {
        if (!searching) return [];
        const q = query.trim().toLowerCase();
        return items
            .filter((c) => label(c).toLowerCase().includes(q))
            .sort((a, b) => (b.started_at || '').localeCompare(a.started_at || ''));
    }, [items, query, searching]);

    const sections = useMemo(() => {
        if (searching) return [];
        const needsIds = new Set(needsYou.map((item) => item.conversation_id));
        const grouped = buildSections(items.filter((item) => !needsIds.has(item.conversation_id)), folders, folderById, '');
        return needsYou.length
            ? [{ key: NEEDS_YOU, kind: 'goals', label: `Needs you · ${needsYou.length}`, items: needsYou }, ...grouped]
            : grouped;
    }, [items, needsYou, folders, folderById, searching]);

    const toggleSection = useCallback((key) => {
        setCollapsed((prev) => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key); else next.add(key);
            persistCollapsed(next);
            return next;
        });
    }, []);

    const closeMenu = useCallback(() => setMenu(null), []);
    const menuConvo = menu ? items.find((c) => c.conversation_id === menu.id) : null;
    const hasRows = sections.some((s) => s.items.length > 0);

    const renderRow = (convo, { showAge = false } = {}) => {
        const id = convo.conversation_id;
        if (renamingId === id) {
            return (
                <RenameRow
                    key={id}
                    convo={convo}
                    onSubmit={(raw) => { setRenamingId(null); actions.renameConversation(convo, raw); }}
                    onCancel={() => setRenamingId(null)}
                />
            );
        }
        return (
            <PhoneConversationRow
                key={id}
                convo={convo}
                running={activity.running.has(id)}
                finished={activity.finished.has(id)}
                showAge={showAge}
                swipeOffset={swipe?.id === id ? swipe.offset : 0}
                deleting={deleting === id}
                onOpen={() => { setSwipe(null); onOpenConversation(id); }}
                onMenu={(rect) => { setSwipe(null); setMenu({ id, rect }); }}
                onSwipe={(offset) => setSwipe(offset ? { id, offset } : null)}
                onTogglePin={() => { setSwipe(null); actions.togglePin(convo); }}
                onArchive={() => { setSwipe(null); actions.archiveConversation(convo); }}
                onDelete={async () => { await actions.deleteConversation(id); setSwipe(null); }}
            />
        );
    };

    return (
        <div className={styles.screen} data-testid="phone-conversation-list">
            <header className={styles.head}>
                <h1 className={styles.heading}>Chats</h1>
                <IconButton
                    size="lg"
                    onClick={onOpenArtifacts}
                    title="Artifacts"
                    aria-label="Artifacts"
                    data-testid="phone-open-artifacts"
                >
                    <i className="bi bi-collection" aria-hidden="true" />
                </IconButton>
            </header>
            <div className={styles.searchRow}>
                <SearchInput
                    value={query}
                    onChange={setQuery}
                    placeholder="Search conversations…"
                    ariaLabel="Search conversations"
                    testId="phone-search"
                />
            </div>
            <div className={styles.list} onScroll={() => swipe && setSwipe(null)}>
                {searching && searchResults.length === 0 && (
                    <div className={styles.empty} data-testid="phone-empty">{`No matches for "${query}"`}</div>
                )}
                {!searching && !loading && !hasRows && (
                    <div className={styles.empty} data-testid="phone-empty">No conversations yet</div>
                )}
                {searching && searchResults.map((convo) => renderRow(convo, { showAge: true }))}
                {!searching && sections.map((section) => {
                    const isCollapsed = section.key !== NEEDS_YOU && collapsed.has(section.key);
                    return (
                        <div key={section.key} className={styles.section} data-section={section.key}>
                            <SectionHeader
                                section={section}
                                collapsed={isCollapsed}
                                collapsible={section.key !== NEEDS_YOU}
                                onToggle={() => toggleSection(section.key)}
                            />
                            {!isCollapsed && section.items.map((convo) => renderRow(convo))}
                        </div>
                    );
                })}
                {!searching && (
                    <ArchivedSection
                        open={showArchived}
                        loaded={actions.archivedLoaded}
                        items={actions.archived}
                        deleting={deleting}
                        onToggle={() => setShowArchived((open) => !open)}
                        onRestore={actions.restoreArchived}
                        onDelete={actions.deleteArchived}
                    />
                )}
            </div>
            <button
                type="button"
                className={styles.newChat}
                onClick={onStartChat}
                aria-label="New chat"
                title="New chat"
                data-testid="phone-new-chat"
            >
                <i className="bi bi-pencil-square" aria-hidden="true" />
            </button>
            {menuConvo && (
                <ConversationMenu
                    convo={menuConvo}
                    rect={menu.rect}
                    folders={folders}
                    deleting={deleting === menuConvo.conversation_id}
                    onClose={closeMenu}
                    onTogglePin={() => { closeMenu(); actions.togglePin(menuConvo); }}
                    onRename={() => { setRenamingId(menuConvo.conversation_id); closeMenu(); }}
                    onMoveToFolder={(folderId) => { actions.moveToFolder(menuConvo, folderId); closeMenu(); }}
                    onArchive={() => { closeMenu(); actions.archiveConversation(menuConvo); }}
                    onDelete={async () => { await actions.deleteConversation(menuConvo.conversation_id); closeMenu(); }}
                />
            )}
        </div>
    );
}
