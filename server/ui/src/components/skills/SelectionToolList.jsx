import { useEffect, useId, useRef, useState } from 'react';

import Popover from '../primitives/Popover.jsx';
import { operationDescription, operationTitle } from '../../features/integrations/components/operationDisplay.js';
import styles from './SelectionToolList.module.css';

/** Read-only labels; the popover only reveals text clipped by the grid. */
function ToolLabel({ title, description }) {
    const id = useId();
    const anchor = useRef(null);
    // A tooltip never takes focus, so dismissal must not move it to the anchor
    // (which would reopen a hover-only tooltip through onFocus).
    const tooltipFocus = useRef(null);
    const hideTimer = useRef(null);
    const [open, setOpen] = useState(false);
    const cancelHide = () => clearTimeout(hideTimer.current);
    const close = () => { cancelHide(); setOpen(false); };
    const show = () => {
        cancelHide();
        const clipped = Array.from(anchor.current.children).some(el => el.scrollWidth > el.clientWidth);
        setOpen(clipped);
    };
    const hideSoon = () => { hideTimer.current = setTimeout(close, 120); };
    useEffect(() => () => clearTimeout(hideTimer.current), []);
    return (
        <li onMouseEnter={show} onMouseLeave={hideSoon}>
            <button ref={anchor} type="button" className={styles.label}
                aria-describedby={open ? id : undefined} onFocus={show} onBlur={close} onClick={show}>
                <span className={styles.title}>{title}</span>
                {description && <span className={styles.description}>{description}</span>}
            </button>
            {open && <Popover anchorRef={anchor} returnFocusRef={tooltipFocus} onClose={close} role="tooltip" ariaLabel={title}
                width={360} maxHeight={240} className={styles.overflow}>
                <div id={id} onMouseEnter={cancelHide} onMouseLeave={hideSoon}>
                    <div className={styles.fullTitle}>{title}</div>
                    {description && <div className={styles.fullDescription}>{description}</div>}
                </div>
            </Popover>}
        </li>
    );
}

export default function SelectionToolList({ category }) {
    const entries = category.operations?.length
        ? category.operations.map(op => ({ id: op.id, title: operationTitle(op),
            description: operationDescription(op) }))
        : (category.tools || []).map(name => ({ id: name, title: name.replaceAll('_', ' '), description: '' }));
    if (!entries.length) return <p>No tools available.</p>;
    return <ul className={styles.grid} aria-label={`${category.label} tools`}>
        {entries.map(entry => <ToolLabel key={entry.id} title={entry.title} description={entry.description} />)}
    </ul>;
}
