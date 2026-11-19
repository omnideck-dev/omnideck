import { useId, useRef, useState } from 'react';

import PaperclipIcon from './icons/PaperclipIcon.jsx';
import Menu from './primitives/Menu.jsx';
import styles from './ComposerAddMenu.module.css';

export default function ComposerAddMenu({ disabled, attachDisabled, onAttach, goalItem }) {
    const [open, setOpen] = useState(false);
    const [initialFocus, setInitialFocus] = useState(0);
    const buttonRef = useRef(null);
    const menuId = useId();
    const shown = open && !disabled;
    const show = (last = false) => {
        if (disabled) return;
        setInitialFocus(last && goalItem ? 1 : 0);
        setOpen(true);
    };
    const items = [
        { id: 'attach', label: 'Attach file', icon: <PaperclipIcon />, disabled: disabled || attachDisabled, onSelect: onAttach },
        ...(goalItem ? [{ id: 'goal', icon: 'bi-bullseye', disabled, ...goalItem }] : []),
    ];
    return <>
        <button
            ref={buttonRef}
            type="button"
            id="fileButton"
            className={styles.addButton}
            onClick={() => (shown ? setOpen(false) : show())}
            onKeyDown={(event) => {
                if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                    event.preventDefault();
                    show(event.key === 'ArrowUp');
                }
            }}
            title="Add to chat"
            aria-label="Add to chat"
            aria-haspopup="menu"
            aria-expanded={shown}
            aria-controls={shown ? menuId : undefined}
            disabled={disabled}
        >
            <i className={`bi bi-plus ${styles.addIcon}`} aria-hidden="true" />
        </button>
        {shown && <Menu
            id={menuId}
            label="Add to chat"
            triggerRef={buttonRef}
            onClose={() => setOpen(false)}
            initialFocus={initialFocus}
            placement="top"
            maxHeight={160}
            testId="composer-add-menu"
            items={items}
        />}
    </>;
}
