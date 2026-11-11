import Popover from './primitives/Popover.jsx';
import styles from './ComposerAutocomplete.module.css';

/**
 * Filtered listbox overlay for a composer shortcut trigger (`/` for skills).
 * Anchored to the textarea itself rather than caret-pixel coordinates — no
 * caret-mirroring needed for v1.
 *
 * Purely presentational: keyboard handling (arrow-key cycling, Enter/Tab
 * commit, Escape close) lives in `ChatInput`'s own `onKeyDown`, not here —
 * that handler runs on every keystroke regardless of this component's mount
 * state, so a commit/dismiss on the same keypress that would otherwise
 * unmount this overlay can't race a document-level listener's own removal.
 *
 * `label`: accessible name of the list, e.g. "Skills".
 * `items`: [{ id, name, description }] — already filtered by the caller.
 * `activeIndex`: currently highlighted row.
 * `onHover(index)`: called when the pointer moves over a row.
 * `onCommit(item)`: called on click of a row.
 * `onClose()`: called on outside-click (via Popover).
 */
export default function ComposerAutocomplete({ anchorRef, label, items, activeIndex, onHover, onCommit, onClose }) {
    if (!items.length) return null;

    return (
        <Popover
            anchorRef={anchorRef}
            onClose={onClose}
            placement="top"
            gap={6}
            role="presentation"
            testId="composer-autocomplete"
            className={styles.popover}
        >
            <div
                className={styles.listbox}
                role="listbox"
                aria-label={label}
            >
                {items.map((item, index) => (
                    <div
                        key={item.id}
                        className={`${styles.option} ${index === activeIndex ? styles.optionActive : ''}`}
                        role="option"
                        aria-selected={index === activeIndex}
                        onMouseEnter={() => onHover(index)}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => onCommit(item)}
                    >
                        <span className={styles.optionName}>{item.name}</span>
                        {item.description && (
                            // The row truncates long descriptions; `title` shows the full text.
                            <span className={styles.optionDescription} title={item.description}>
                                {item.description}
                            </span>
                        )}
                    </div>
                ))}
            </div>
        </Popover>
    );
}
