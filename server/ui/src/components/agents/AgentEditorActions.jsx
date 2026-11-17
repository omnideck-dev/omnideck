import { useRef, useState } from 'react';
import Button from '../primitives/Button.jsx';
import ConfirmButton from '../primitives/ConfirmButton.jsx';
import IconButton from '../primitives/IconButton.jsx';
import Popover from '../primitives/Popover.jsx';
import styles from '../ProfileBuilder.module.css';

export default function AgentEditorActions({ onDuplicate, onExport, onDelete, disabled }) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef(null);
    const contentRef = useRef(null);
    const focusLast = useRef(false);
    const focusInitialItem = () => {
        const items = contentRef.current?.querySelectorAll('[role="menuitem"]:not(:disabled)');
        (focusLast.current ? items?.[items.length - 1] : items?.[0])?.focus();
    };
    const close = () => { setOpen(false); anchorRef.current?.querySelector('button')?.focus(); };
    const handleKeyDown = event => {
        if (event.key === 'Tab') {
            event.preventDefault();
            // The portal sits at the end of body. Continue from the trigger's
            // document position, not from the menu's unrelated portal position.
            const trigger = anchorRef.current.querySelector('button');
            const stops = Array.from(document.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]'))
                .filter(element => {
                    if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert]')) return false;
                    for (let node = element; node; node = node.parentElement) {
                        const style = getComputedStyle(node);
                        if (style.display === 'none' || style.visibility === 'hidden') return false;
                    }
                    return true;
                });
            const next = stops[stops.indexOf(trigger) + (event.shiftKey ? -1 : 1)];
            close();
            next?.focus();
            return;
        }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = Array.from(contentRef.current.querySelectorAll('[role="menuitem"]:not(:disabled)'));
        const current = items.indexOf(document.activeElement);
        const next = { ArrowDown: (current + 1) % items.length, ArrowUp: (current - 1 + items.length) % items.length,
            Home: 0, End: items.length - 1 }[event.key];
        items[next]?.focus();
    };
    return <>
        <span ref={anchorRef} className={styles.overflowAction}>
            <IconButton size="md" aria-label="More actions" aria-haspopup="menu" aria-expanded={open}
                disabled={disabled} onClick={() => { focusLast.current = false; setOpen(value => !value); }}
                onKeyDown={event => {
                    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                    event.preventDefault();
                    focusLast.current = event.key === 'ArrowUp';
                    setOpen(true);
                }}><i className="bi bi-three-dots" aria-hidden="true" /></IconButton>
        </span>
        {open && <Popover anchorRef={anchorRef} returnFocusRef={{ current: anchorRef.current?.querySelector('button') }} onClose={close} onOpen={focusInitialItem} width={200} align="end" role="menu" ariaLabel="Agent actions" className={styles.editorPopover}>
            <div className={styles.moreActions} ref={contentRef} onKeyDown={handleKeyDown}>
                <Button variant="menuItem" role="menuitem" tabIndex={-1} onClick={() => { close(); onDuplicate(); }}><i className="bi bi-copy" aria-hidden="true" /> Duplicate</Button>
                <Button variant="menuItem" role="menuitem" tabIndex={-1} data-testid="profile-export" onClick={() => { close(); onExport(); }}><i className="bi bi-download" aria-hidden="true" /> Export…</Button>
                <div role="separator" className={styles.actionSeparator} />
                <ConfirmButton appearance="menuItem" role="menuitem" tabIndex={-1} label="Delete agent" aria-label="Delete agent" confirmLabel="Confirm delete?" busyLabel="Deleting…" icon="bi-trash"
                    onConfirm={async () => { await onDelete(); close(); }} />
            </div>
        </Popover>}
    </>;
}
