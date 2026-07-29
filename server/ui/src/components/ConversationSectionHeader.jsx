import { DEFAULT_FOLDER_ICON } from './conversationSections.js';
import styles from './ConversationSectionHeader.module.css';

/**
 * A collapsible section header. Pinned and date buckets show just a label;
 * folder headers put the folder's icon inline (like the pin) and add a 3-dot
 * button that opens the folder menu. Clicking the label toggles the section's
 * collapsed state. The folder ⋮ follows conversation rows: it appears on
 * hover, focus, or while the menu is open. Right-clicking anywhere on a folder
 * header opens that same menu.
 */
export default function ConversationSectionHeader({ section, collapsed, menuOpen, onToggle, onOpenFolderMenu }) {
    const isFolder = section.kind === 'folder';
    return (
        <div
            className={[
                styles.dayLabel,
                isFolder ? styles.folderHead : '',
                menuOpen ? styles.menuOpen : '',
            ].filter(Boolean).join(' ')}
            onContextMenu={(event) => {
                if (!isFolder) return;
                event.preventDefault();
                event.stopPropagation();
                onOpenFolderMenu({
                    left: event.clientX,
                    right: event.clientX,
                    top: event.clientY,
                    bottom: event.clientY,
                });
            }}
            data-testid={isFolder ? 'recent-folder-header' : undefined}
        >
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
