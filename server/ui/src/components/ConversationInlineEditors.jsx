import { useEffect, useRef, useState } from 'react';

import { MAX_TITLE_LEN, MAX_FOLDER_NAME_LEN, renameSeed } from './conversationSections.js';
import styles from './ConversationInlineEditors.module.css';

/**
 * A small auto-focused text input for naming things inline (new folder, folder
 * rename). Enter submits, Escape cancels, blur submits. A trailing blur after
 * an explicit commit is guarded so it doesn't double-fire.
 */
export function InlineNameInput({ seed = '', placeholder, onSubmit, onCancel, testId, bare = false }) {
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
export function RenameRow({ convo, onSubmit, onCancel }) {
    const seed = renameSeed(convo);
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
