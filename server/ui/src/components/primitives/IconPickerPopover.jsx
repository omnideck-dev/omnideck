import { useEffect, useMemo, useRef } from 'react';

import Popover from './Popover.jsx';
import styles from './IconPickerPopover.module.css';

function virtualAnchor(rect) {
    return {
        contains: () => false,
        getBoundingClientRect: () => rect,
    };
}

/**
 * Canonical SIGNAL popover for choosing one icon from a curated Bootstrap set.
 *
 * Use `anchorRef` when the trigger remains mounted. `anchorRect` supports
 * menus that close their trigger before opening the picker, such as folders.
 */
export default function IconPickerPopover({
    anchorRef,
    anchorRect,
    returnFocusRef,
    icons,
    current,
    onPick,
    onClose,
    ariaLabel = 'Choose an icon',
    testId,
    optionTestId,
}) {
    const virtualAnchorRef = useMemo(
        () => ({ current: virtualAnchor(anchorRect) }),
        [anchorRect],
    );
    const resolvedAnchorRef = anchorRef || virtualAnchorRef;
    const optionRefs = useRef([]);
    const selectedIndex = Math.max(0, icons.indexOf(current));

    useEffect(() => {
        optionRefs.current[selectedIndex]?.focus();
    }, [selectedIndex]);

    const moveFocus = (event, index) => {
        let next = null;
        if (event.key === 'ArrowRight') next = (index + 1) % icons.length;
        if (event.key === 'ArrowLeft') next = (index - 1 + icons.length) % icons.length;
        if (event.key === 'ArrowDown') next = (index + 6) % icons.length;
        if (event.key === 'ArrowUp') next = (index - 6 + icons.length) % icons.length;
        if (event.key === 'Home') next = 0;
        if (event.key === 'End') next = icons.length - 1;
        if (next === null) return;
        event.preventDefault();
        optionRefs.current[next]?.focus();
    };

    return (
        <Popover
            anchorRef={resolvedAnchorRef}
            returnFocusRef={returnFocusRef || resolvedAnchorRef}
            onClose={onClose}
            width={236}
            maxHeight={280}
            flipThreshold={220}
            role="menu"
            ariaLabel={ariaLabel}
            testId={testId}
            className={styles.popover}
        >
            <div className={styles.grid}>
                {icons.map((icon, index) => (
                    <button
                        ref={(node) => { optionRefs.current[index] = node; }}
                        key={icon}
                        type="button"
                        role="menuitemradio"
                        className={`${styles.option} ${icon === current ? styles.selected : ''}`}
                        onClick={() => onPick(icon)}
                        onKeyDown={(event) => moveFocus(event, index)}
                        aria-label={icon.replace('bi-', '').replaceAll('-', ' ')}
                        aria-checked={icon === current}
                        data-testid={typeof optionTestId === 'function' ? optionTestId(icon) : optionTestId}
                        data-icon={icon}
                    >
                        <i className={`bi ${icon}`} aria-hidden="true" />
                    </button>
                ))}
            </div>
        </Popover>
    );
}
