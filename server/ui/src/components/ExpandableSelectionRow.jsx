import { useId, useState } from 'react';

import IconButton from './primitives/IconButton.jsx';
import styles from './ExpandableSelectionRow.module.css';

/** Selected item disclosure; the parent owns selection and removal. */
export default function ExpandableSelectionRow({ icon, name, description, meta, onRemove, children, testId }) {
    const id = useId();
    const [expanded, setExpanded] = useState(false);
    return (
        <li className={styles.row} data-testid={testId}>
            <div className={styles.header}>
                <button type="button" className={styles.toggle}
                    aria-expanded={expanded} aria-controls={`${id}-content`}
                    aria-labelledby={`${id}-name`} aria-describedby={description ? `${id}-description` : undefined}
                    onClick={() => setExpanded(current => !current)}>
                    <span className={styles.icon} aria-hidden="true">{icon}</span>
                    <span className={styles.info}>
                        <span id={`${id}-name`} className={styles.name}>{name}</span>
                        {description && <span id={`${id}-description`} className={styles.description}>{description}</span>}
                        {meta && <span className={styles.meta}>{meta}</span>}
                    </span>
                    <span className={styles.actionSlot} data-selection-action="expand" aria-hidden="true">
                        <i className={`bi ${expanded ? 'bi-chevron-down' : 'bi-chevron-right'} ${styles.actionIcon}`} />
                    </span>
                </button>
                <IconButton size="md" aria-label={`Remove ${name}`} onClick={onRemove} data-selection-action="remove">
                    <i className={`bi bi-x-lg ${styles.actionIcon}`} aria-hidden="true" />
                </IconButton>
            </div>
            <div id={`${id}-content`} className={styles.body} hidden={!expanded}>{children}</div>
        </li>
    );
}
