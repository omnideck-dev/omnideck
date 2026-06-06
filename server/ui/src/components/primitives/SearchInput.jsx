import styles from './SearchInput.module.css';

/**
 * Canonical search field (SIGNAL design language: the `.input` control with a
 * leading bi-search glyph and a focus-glow ring). Use this everywhere a search
 * box is needed rather than hand-rolling one, so they stay consistent.
 *
 * Props:
 *   value        — controlled text
 *   onChange     — (value) => void  (receives the string, not the event)
 *   placeholder  — placeholder text
 *   ariaLabel    — accessible label (optional)
 *   testId       — data-testid for the input (optional)
 *   clearTestId  — data-testid for the clear button (optional)
 *   clearable    — show a clear (✕) button when non-empty (default true)
 *   className    — merged onto the container for layout/spacing (optional)
 */
export default function SearchInput({
    value,
    onChange,
    placeholder,
    ariaLabel,
    testId,
    clearTestId,
    clearable = true,
    className,
}) {
    return (
        <div className={[styles.search, className].filter(Boolean).join(' ')}>
            <i className={`bi bi-search ${styles.icon}`} aria-hidden="true" />
            <input
                type="search"
                className={styles.input}
                value={value}
                placeholder={placeholder}
                aria-label={ariaLabel}
                data-testid={testId}
                onChange={(event) => onChange(event.target.value)}
            />
            {clearable && value && (
                <button
                    type="button"
                    className={styles.clear}
                    onClick={() => onChange('')}
                    title="Clear search"
                    aria-label="Clear search"
                    data-testid={clearTestId}
                >
                    <i className="bi bi-x-lg" aria-hidden="true" />
                </button>
            )}
        </div>
    );
}
