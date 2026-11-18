import { useRef } from 'react';

import Button from './Button.jsx';
import ConfirmButton from './ConfirmButton.jsx';
import Popover from './Popover.jsx';
import styles from './Menu.module.css';

const FOCUSABLE = 'button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]):not([type="file"]), select:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])';

function focusBeside(trigger, backwards) {
    const controls = Array.from(document.querySelectorAll(FOCUSABLE));
    const index = controls.indexOf(trigger);
    (controls[index + (backwards ? -1 : 1)] || trigger)?.focus();
}

export default function Menu({
    triggerRef, onClose, items, label, id, initialFocus = 0, width = 232, align = 'start', placement = 'bottom',
    maxHeight, testId,
}) {
    const contentRef = useRef(null);
    const enabledItems = () => Array.from(contentRef.current?.querySelectorAll('[role="menuitem"]:not(:disabled)') || []);
    const focusInitial = () => {
        const list = enabledItems();
        list[Math.min(initialFocus, list.length - 1)]?.focus();
    };
    const close = () => {
        onClose();
        triggerRef.current?.focus();
    };
    const onKeyDown = (event) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopPropagation();
            close();
            return;
        }
        if (event.key === 'Tab') {
            event.preventDefault();
            onClose();
            focusBeside(triggerRef.current, event.shiftKey);
            return;
        }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const list = enabledItems();
        const current = list.indexOf(document.activeElement);
        const next = {
            ArrowDown: (current + 1) % list.length,
            ArrowUp: (current - 1 + list.length) % list.length,
            Home: 0,
            End: list.length - 1,
        }[event.key];
        list[next]?.focus();
    };
    return <Popover anchorRef={triggerRef} returnFocusRef={triggerRef} onClose={onClose} onOpen={focusInitial}
        width={width} align={align} placement={placement} maxHeight={maxHeight} className={styles.menu} testId={testId}>
        <div id={id} role="menu" aria-label={label} className={styles.items} ref={contentRef} onKeyDown={onKeyDown}>
            {items.map((item) => <div key={item.id} className={styles.slot}>
                {item.separatorBefore && <div role="separator" className={styles.separator} />}
                {item.confirm
                    ? <ConfirmButton appearance="menuItem" role="menuitem" tabIndex={-1} label={item.label} icon={item.icon}
                        disabled={item.disabled} {...item.confirm} />
                    : <Button variant="menuItem" role="menuitem" tabIndex={-1} disabled={item.disabled}
                        onClick={() => { onClose(); triggerRef.current?.focus(); item.onSelect(); }}>
                        {typeof item.icon === 'string' ? <i className={`bi ${item.icon}`} aria-hidden="true" /> : item.icon}
                        {item.label}
                        {item.shortcut && <span className={styles.shortcut}>{item.shortcut}</span>}
                    </Button>}
            </div>)}
        </div>
    </Popover>;
}
