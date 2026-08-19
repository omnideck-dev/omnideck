import {
    useCallback,
    useEffect,
    useId,
    useMemo,
    useRef,
    useState,
} from 'react';

import Popover from './Popover.jsx';
import styles from './Select.module.css';

const TYPEAHEAD_RESET_MS = 500;

function firstEnabledIndex(options) {
    return options.findIndex((option) => !option.disabled);
}

function lastEnabledIndex(options) {
    for (let index = options.length - 1; index >= 0; index -= 1) {
        if (!options[index].disabled) return index;
    }
    return -1;
}

function nextEnabledIndex(options, current, direction) {
    if (!options.length) return -1;
    for (let offset = 1; offset <= options.length; offset += 1) {
        const index = (current + (direction * offset) + options.length) % options.length;
        if (!options[index].disabled) return index;
    }
    return -1;
}

/**
 * SIGNAL select-only combobox.
 *
 * The trigger and listbox are both application-rendered so their presentation
 * is identical in WKWebView, WebView2, and WebKitGTK. DOM focus remains on the
 * trigger while `aria-activedescendant` exposes keyboard focus in the listbox.
 *
 * options: [{ value, label, disabled? }]
 * onChange: (value, option) => void
 */
export default function Select({
    options = [],
    value,
    defaultValue = '',
    onChange,
    disabled = false,
    placeholder = 'Select…',
    ariaLabel,
    ariaLabelledBy,
    ariaDescribedBy,
    className = '',
    id,
    name,
    testId,
    menuTestId,
    maxMenuHeight = 320,
}) {
    const generatedId = useId();
    const triggerId = id || `select-${generatedId}`;
    const listboxId = `${triggerId}-listbox`;
    const controlled = value !== undefined;
    const [internalValue, setInternalValue] = useState(defaultValue);
    const selectedValue = controlled ? value : internalValue;
    const selectedIndex = options.findIndex((option) => option.value === selectedValue);
    const selectedOption = selectedIndex >= 0 ? options[selectedIndex] : null;

    const [open, setOpen] = useState(false);
    const [activeIndex, setActiveIndex] = useState(() => (
        selectedIndex >= 0 ? selectedIndex : firstEnabledIndex(options)
    ));
    const triggerRef = useRef(null);
    const optionRefs = useRef([]);
    const typeaheadRef = useRef({ value: '', timeout: null });

    const optionIds = useMemo(
        () => options.map((_, index) => `${listboxId}-option-${index}`),
        [listboxId, options],
    );

    const close = useCallback(() => setOpen(false), []);

    const openMenu = useCallback(() => {
        if (disabled || firstEnabledIndex(options) < 0) return;
        setActiveIndex(selectedIndex >= 0 && !options[selectedIndex]?.disabled
            ? selectedIndex
            : firstEnabledIndex(options));
        setOpen(true);
    }, [disabled, options, selectedIndex]);

    const choose = useCallback((index) => {
        const option = options[index];
        if (!option || option.disabled) return;
        if (!controlled) setInternalValue(option.value);
        onChange?.(option.value, option);
        setActiveIndex(index);
        setOpen(false);
        triggerRef.current?.focus();
    }, [controlled, onChange, options]);

    const handleTypeahead = useCallback((key) => {
        const state = typeaheadRef.current;
        window.clearTimeout(state.timeout);
        state.value += key.toLocaleLowerCase();

        const matchIndex = options.findIndex((option) => (
            !option.disabled
            && String(option.label).toLocaleLowerCase().startsWith(state.value)
        ));
        if (matchIndex >= 0) {
            if (open) setActiveIndex(matchIndex);
            else choose(matchIndex);
        }

        state.timeout = window.setTimeout(() => {
            state.value = '';
            state.timeout = null;
        }, TYPEAHEAD_RESET_MS);
    }, [choose, open, options]);

    const handleKeyDown = useCallback((event) => {
        if (disabled) return;

        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!open) {
                openMenu();
                return;
            }
            const direction = event.key === 'ArrowDown' ? 1 : -1;
            setActiveIndex((current) => nextEnabledIndex(options, current, direction));
            return;
        }

        if (event.key === 'Home' && open) {
            event.preventDefault();
            setActiveIndex(firstEnabledIndex(options));
            return;
        }

        if (event.key === 'End' && open) {
            event.preventDefault();
            setActiveIndex(lastEnabledIndex(options));
            return;
        }

        if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (open) choose(activeIndex);
            else openMenu();
            return;
        }

        if (event.key === 'Escape' && open) {
            event.preventDefault();
            close();
            triggerRef.current?.focus();
            return;
        }

        if (event.key === 'Tab' && open) {
            close();
            return;
        }

        if (!event.altKey && !event.ctrlKey && !event.metaKey && event.key.length === 1) {
            handleTypeahead(event.key);
        }
    }, [activeIndex, choose, close, disabled, handleTypeahead, open, openMenu, options]);

    useEffect(() => () => {
        window.clearTimeout(typeaheadRef.current.timeout);
    }, []);

    useEffect(() => {
        if (open && (activeIndex < 0 || options[activeIndex]?.disabled)) {
            setActiveIndex(selectedIndex >= 0 && !options[selectedIndex]?.disabled
                ? selectedIndex
                : firstEnabledIndex(options));
        }
    }, [activeIndex, open, options, selectedIndex]);

    useEffect(() => {
        if (!open || activeIndex < 0) return;
        optionRefs.current[activeIndex]?.scrollIntoView?.({ block: 'nearest' });
    }, [activeIndex, open]);

    const activeOptionId = open && activeIndex >= 0 ? optionIds[activeIndex] : undefined;

    return (
        <div className={`${styles.root} ${className}`}>
            {name && <input type="hidden" name={name} value={selectedValue ?? ''} />}
            <button
                ref={triggerRef}
                id={triggerId}
                type="button"
                className={`${styles.trigger} ${open ? styles.triggerOpen : ''}`}
                role="combobox"
                aria-label={ariaLabel}
                aria-labelledby={ariaLabelledBy}
                aria-describedby={ariaDescribedBy}
                aria-haspopup="listbox"
                aria-autocomplete="none"
                aria-controls={listboxId}
                aria-expanded={open}
                aria-activedescendant={activeOptionId}
                aria-disabled={disabled || undefined}
                disabled={disabled}
                onClick={() => (open ? close() : openMenu())}
                onKeyDown={handleKeyDown}
                data-testid={testId}
                data-value={selectedValue ?? ''}
            >
                <span className={selectedOption ? styles.value : styles.placeholder}>
                    {selectedOption?.label ?? placeholder}
                </span>
                <span className={styles.caret} aria-hidden="true">
                    <svg viewBox="0 0 10 6" focusable="false">
                        <path d="M1 1l4 4 4-4" />
                    </svg>
                </span>
            </button>

            {open && (
                <Popover
                    anchorRef={triggerRef}
                    returnFocusRef={triggerRef}
                    onClose={close}
                    gap={4}
                    maxHeight={maxMenuHeight}
                    flipThreshold={160}
                    role="presentation"
                    testId={menuTestId || (testId ? `${testId}-menu` : undefined)}
                    className={styles.popover}
                >
                    <div
                        id={listboxId}
                        className={styles.listbox}
                        role="listbox"
                        aria-label={ariaLabel ? `${ariaLabel} options` : undefined}
                        aria-labelledby={!ariaLabel ? ariaLabelledBy : undefined}
                    >
                        {options.map((option, index) => {
                            const selected = index === selectedIndex;
                            const active = index === activeIndex;
                            return (
                                <div
                                    ref={(node) => { optionRefs.current[index] = node; }}
                                    key={String(option.value)}
                                    id={optionIds[index]}
                                    className={`${styles.option} ${selected ? styles.optionSelected : ''} ${active ? styles.optionActive : ''} ${option.disabled ? styles.optionDisabled : ''}`}
                                    role="option"
                                    aria-selected={selected}
                                    aria-disabled={option.disabled || undefined}
                                    onMouseEnter={() => {
                                        if (!option.disabled) setActiveIndex(index);
                                    }}
                                    onMouseDown={(event) => event.preventDefault()}
                                    onClick={() => choose(index)}
                                    data-value={option.value}
                                >
                                    <span className={styles.optionLabel}>{option.label}</span>
                                    <span className={styles.check} aria-hidden="true">
                                        {selected ? '✓' : ''}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </Popover>
            )}
        </div>
    );
}
