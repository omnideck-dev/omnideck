import styles from './SlashHint.module.css';

/**
 * One-row command hint shown above a composer while its text starts with "/".
 * Focus stays in the text box: the composer picks the command on Enter and
 * dismisses the hint on Escape. Clicking the row also picks it.
 */
export default function SlashHint({ id, command, description, onPick }) {
    return <div id={id} className={styles.hint} role="listbox" aria-label="Commands" data-testid="slash-hint">
        <div className={styles.option} role="option" aria-selected="true" tabIndex={-1}
            onMouseDown={(event) => event.preventDefault()} onClick={onPick}>
            <span className={styles.command}>{command}</span>
            <span className={styles.description}>{description}</span>
            <span className={styles.key} aria-hidden="true">Enter</span>
        </div>
    </div>;
}
