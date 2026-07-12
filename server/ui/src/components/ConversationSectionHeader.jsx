import { DEFAULT_FOLDER_ICON } from './conversationSections.js';
import styles from './ConversationSectionHeader.module.css';

/**
 * A collapsible section header. Pinned and date buckets show a label + count;
 * folder headers put the folder's icon inline (like the pin) and add a hover
 * 3-dot button that opens the folder menu. Clicking the label toggles the
 * section's collapsed state. The count and the folder ⋮ share the trailing
 * slot: on folder hover / menu-open the count hides and the ⋮ takes its place,
 * so counts stay aligned across every section with no reserved gap.
 */
export default function ConversationSectionHeader({ section, collapsed, menuOpen, onToggle, onOpenFolderMenu }) {
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
