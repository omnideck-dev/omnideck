import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import ConfirmButton from './primitives/ConfirmButton.jsx';
import IconPickerPopover from './primitives/IconPickerPopover.jsx';
import { MENU_WIDTH, DEFAULT_FOLDER_ICON, FOLDER_ICONS } from './conversationSections.js';
import styles from './ConversationMenus.module.css';

/**
 * The 3-dot conversation context menu, portaled to <body> so the sidebar's
 * overflow can't clip it. Anchored under the trigger, right-aligned to it,
 * flipping above when there isn't room below. Closes on outside click or
 * Escape. The "Move to folder" item expands an inline picker of folders.
 */
export function ConversationMenu({ convo, rect, folders, deleting, onClose, onTogglePin, onRename, onMoveToFolder, onArchive, onDelete }) {
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
 * The folder options menu, portaled to <body>. Collapses the folder's actions —
 * change icon, rename, delete — behind one 3-dot trigger so the header stays
 * uncluttered. Closes on outside click or Escape.
 */
export function FolderMenu({ rect, onClose, onChangeIcon, onRename, onDelete }) {
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
 * Portaled grid of curated Bootstrap icons for choosing a folder's icon.
 * Anchored under the trigger, flipping above / clamping to the viewport when
 * there isn't room. Closes on outside click or Escape.
 */
export function IconPicker({ rect, current, onPick, onClose }) {
    return (
        <IconPickerPopover
            anchorRect={rect}
            icons={FOLDER_ICONS}
            current={current}
            onPick={onPick}
            onClose={onClose}
            ariaLabel="Choose folder icon"
            testId="recent-icon-picker"
            optionTestId="recent-icon-option"
        />
    );
}
