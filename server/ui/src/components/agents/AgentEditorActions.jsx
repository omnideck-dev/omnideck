import { useRef, useState } from 'react';
import IconButton from '../primitives/IconButton.jsx';
import Menu from '../primitives/Menu.jsx';
import styles from '../ProfileBuilder.module.css';

export default function AgentEditorActions({ onDuplicate, onExport, onDelete, disabled }) {
    const [open, setOpen] = useState(false);
    const [initialFocus, setInitialFocus] = useState(0);
    const triggerRef = useRef(null);
    const close = () => setOpen(false);
    const items = [
        { id: 'duplicate', label: 'Duplicate', icon: 'bi-copy', onSelect: onDuplicate },
        { id: 'export', label: 'Export…', icon: 'bi-download', testId: 'profile-export', onSelect: onExport },
        {
            id: 'delete', label: 'Delete agent', icon: 'bi-trash', separatorBefore: true, confirm: {
                'aria-label': 'Delete agent', confirmLabel: 'Confirm delete?', busyLabel: 'Deleting…',
                onConfirm: async () => { await onDelete(); close(); triggerRef.current?.focus(); },
            },
        },
    ];
    return <>
        <span className={styles.overflowAction}>
            <IconButton ref={triggerRef} size="md" aria-label="More actions" aria-haspopup="menu" aria-expanded={open}
                disabled={disabled} onClick={() => { setInitialFocus(0); setOpen(value => !value); }}
                onKeyDown={event => {
                    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
                    event.preventDefault();
                    setInitialFocus(event.key === 'ArrowUp' ? items.length - 1 : 0);
                    setOpen(true);
                }}><i className="bi bi-three-dots" aria-hidden="true" /></IconButton>
        </span>
        {open && <Menu triggerRef={triggerRef} onClose={close} label="Agent actions" items={items} width={200}
            align="end" initialFocus={initialFocus} />}
    </>;
}
