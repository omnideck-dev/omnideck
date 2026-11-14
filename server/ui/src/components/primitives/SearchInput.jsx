import { useRef, useState } from 'react';
import Button from './Button.jsx';
import IconButton from './IconButton.jsx';
import Popover from './Popover.jsx';
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
 *   disabled     — disable editing and clearing (default false)
 *   className    — merged onto the container for layout/spacing (optional)
 *   filters      — optional [{ id, label, chip, icon, count }]. Adds a filter
 *                  button that opens a single-choice menu; the chosen filter
 *                  shows as a removable chip (its `chip` text, else `label`)
 *                  before the text.
 *   filter       — id of the chosen filter, or null for none
 *   onFilterChange — (id | null) => void
 *   filterTestId — data-testid base for the filter button, menu, options and chip
 */
export default function SearchInput({
    value,
    onChange,
    placeholder,
    ariaLabel,
    testId,
    clearTestId,
    clearable = true,
    disabled = false,
    className,
    filters,
    filter = null,
    onFilterChange,
    filterTestId,
}) {
    const active = filters?.find((f) => f.id === filter);
    return (
        <div className={[
            styles.search,
            disabled ? styles.disabled : '',
            className,
        ].filter(Boolean).join(' ')}>
            <i className={`bi bi-search ${styles.icon}`} aria-hidden="true" />
            {active && (
                <span className={styles.chip} data-testid={filterTestId && `${filterTestId}-chip`}>
                    {active.chip || active.label}
                    <button
                        type="button"
                        className={styles.chipClear}
                        onClick={() => onFilterChange(null)}
                        disabled={disabled}
                        title="Clear filter"
                        aria-label={`Clear ${active.chip || active.label} filter`}
                    >
                        <i className="bi bi-x-lg" aria-hidden="true" />
                    </button>
                </span>
            )}
            <input
                type="search"
                className={styles.input}
                value={value}
                placeholder={active ? 'Search…' : placeholder}
                aria-label={ariaLabel}
                data-testid={testId}
                onChange={(event) => onChange(event.target.value)}
                disabled={disabled}
            />
            {clearable && value && !disabled && (
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
            {filters?.length > 0 && (
                <FilterMenu filters={filters} filter={filter} onChange={onFilterChange} disabled={disabled} testId={filterTestId} />
            )}
        </div>
    );
}

function FilterMenu({ filters, filter, onChange, disabled, testId }) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef(null);
    const triggerRef = useRef(null);
    const listRef = useRef(null);
    const focusLast = useRef(false);
    const options = [{ id: null, label: 'All' }, ...filters];

    const close = () => { setOpen(false); triggerRef.current?.focus(); };
    const pick = (id) => { close(); onChange(id); };
    const focusInitial = () => {
        const items = listRef.current?.querySelectorAll('[role="menuitemradio"]');
        const checked = listRef.current?.querySelector('[aria-checked="true"]');
        (focusLast.current ? items?.[items.length - 1] : checked || items?.[0])?.focus();
    };
    const handleKeyDown = (event) => {
        // Focus returns to the trigger before the browser handles Tab, so Tab
        // moves on from the search field instead of from the end of the page.
        if (event.key === 'Tab') { close(); return; }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = Array.from(listRef.current.querySelectorAll('[role="menuitemradio"]'));
        const current = items.indexOf(document.activeElement);
        const next = {
            ArrowDown: (current + 1) % items.length,
            ArrowUp: (current - 1 + items.length) % items.length,
            Home: 0,
            End: items.length - 1,
        }[event.key];
        items[next]?.focus();
    };

    return (
        <span ref={anchorRef} className={styles.filterAnchor}>
            <IconButton
                ref={triggerRef}
                size="xs"
                onClick={() => { focusLast.current = false; setOpen((value) => !value); }}
                onKeyDown={(event) => {
                    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                    event.preventDefault();
                    focusLast.current = event.key === 'ArrowUp';
                    setOpen(true);
                }}
                disabled={disabled}
                aria-haspopup="menu"
                aria-expanded={open}
                title="Filter"
                aria-label="Filter"
                data-testid={testId}
            >
                <i className="bi bi-funnel" aria-hidden="true" />
            </IconButton>
            {open && (
                <Popover
                    anchorRef={anchorRef}
                    triggerRef={triggerRef}
                    onClose={close}
                    onOpen={focusInitial}
                    align="end"
                    width={200}
                    role="menu"
                    ariaLabel="Filter"
                    className={styles.popover}
                    testId={testId && `${testId}-menu`}
                >
                    <div className={styles.menu} ref={listRef} onKeyDown={handleKeyDown}>
                        {options.map((option) => (
                            <Button
                                key={option.id ?? 'all'}
                                variant="menuItem"
                                role="menuitemradio"
                                aria-checked={filter === option.id}
                                tabIndex={-1}
                                onClick={() => pick(option.id)}
                                data-testid={testId && `${testId}-option`}
                                data-filter={option.id ?? ''}
                            >
                                <i className={`bi ${option.icon || 'bi-list-ul'}`} aria-hidden="true" />
                                <span className={styles.optionLabel}>{option.label}</span>
                                {filter === option.id
                                    ? <i className={`bi bi-check2 ${styles.check}`} aria-hidden="true" />
                                    : option.count != null && <span className={styles.count}>{option.count}</span>}
                            </Button>
                        ))}
                    </div>
                </Popover>
            )}
        </span>
    );
}
