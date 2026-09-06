import { useEffect, useId, useRef, useState } from 'react';
import Popover from '../../../components/primitives/Popover.jsx';
import { formatTokens } from '../../../utils/agentUtils.js';
import styles from './ConversationDetails.module.css';

function readSeen(key) {
    try {
        const value = JSON.parse(localStorage.getItem(key) || '[]');
        return new Set(Array.isArray(value) ? value.filter((id) => typeof id === 'string') : []);
    } catch { return new Set(); }
}

function ResourceRow({ row, grouped = false, isNew, onSelect }) {
    return <button className={styles.row}
        aria-label={grouped ? `${row.ownerLabel} ${row.resourceId === 'browser' ? 'Browser' : 'Terminal'}${isNew ? ' · New' : ''}` : undefined}
        data-testid={row.id === 'artifacts' ? 'conversation-artifacts-trigger' : row.id === 'agents' ? 'network-indicator' : undefined}
        onClick={() => onSelect(row)}>
        {!grouped && <span className={styles.icon}><i className={`bi bi-${row.icon}`} aria-hidden="true" /></span>}
        <span className={styles.copy}><strong>{grouped ? row.ownerLabel : row.label} {row.count != null && <span className={styles.count}>{row.count}</span>}</strong>{row.description && <span>{row.description}</span>}</span>
        {isNew && <span className={styles.badge}>New</span>}
        <i className={`bi bi-chevron-right ${styles.chevron}`} aria-hidden="true" />
    </button>;
}

function ResourceList({ rows, seen, openingUpdates, onSelect }) {
    const renderRow = (row, grouped = false) => <ResourceRow key={row.id} row={row} grouped={grouped}
        isNew={row.updateIds.some((id) => openingUpdates.has(id) || !seen.has(id))} onSelect={onSelect} />;
    return <div className={styles.resources}>
        {rows.filter((row) => !row.resourceId).map((row) => renderRow(row))}
        {['browser', 'terminal'].map((resourceId) => {
            const items = rows.filter((row) => row.resourceId === resourceId);
            if (!items.length) return null;
            if (items.length === 1 && items[0].isRoot) return renderRow(items[0]);
            const label = resourceId === 'browser' ? 'Browsers' : 'Terminals';
            return <section key={resourceId} className={styles.resourceGroup} aria-label={label}>
                <h3 className={styles.groupHeading}><i className={`bi bi-${resourceId === 'browser' ? 'globe' : 'terminal'}`} aria-hidden="true" />{label}</h3>
                <div className={styles.groupRows}>{items.map((row) => renderRow(row, true))}</div>
            </section>;
        })}
    </div>;
}

function AdvancedStats({ model }) {
    const context = model.contextUsage;
    const limit = context?.context_limit || 0;
    const used = context?.context_used || 0;
    const threshold = context?.compaction_threshold ?? 0.75;
    const remaining = Math.max(0, Math.round(limit * threshold - used));
    return (
        <details className={styles.advanced}>
            <summary>Advanced <span>Turns, tokens, cost, and context</span></summary>
            <dl className={styles.stats}>
                <div><dt>Turns</dt><dd data-testid="chat-turns">{model.turnCount}</dd></div>
                <div><dt>Tokens used</dt><dd>{formatTokens(model.totalTokens) ?? '—'}</dd></div>
                <div><dt>Est. cost</dt><dd>—</dd></div>
                <div><dt>Sub-agents</dt><dd>{model.agentCount}</dd></div>
            </dl>
            {limit > 0 && <div className={styles.context}>
                <div>Primary context <span>{Math.round(used / limit * 100)}% used</span></div>
                <progress aria-label="Primary context used" value={Math.min(used, limit)} max={limit} />
                <small>{remaining ? `About ${formatTokens(remaining)} tokens until compaction` : 'Compaction threshold reached'}</small>
            </div>}
            <table className={styles.usage}>
                <caption>Usage by agent</caption>
                <thead><tr><th scope="col">Agent</th><th scope="col">Tokens</th><th scope="col">Cost</th></tr></thead>
                <tbody>{model.agentUsage.map((agent) => <tr key={agent.id}>
                    <th scope="row">{agent.label}</th><td>{formatTokens(agent.tokens) ?? '—'}</td><td>—</td>
                </tr>)}</tbody>
            </table>
        </details>
    );
}

/** Keyed by conversation by its parent, including its acknowledgement state. */
export default function ConversationDetails({ conversationId, model, onSelect }) {
    const [open, setOpen] = useState(false);
    const storageKey = `omnideck:details-seen:${conversationId || 'draft'}`;
    const [seen, setSeen] = useState(() => readSeen(storageKey));
    const [openingUpdates, setOpeningUpdates] = useState(new Set());
    const container = useRef(null);
    const trigger = useRef(null);
    const panel = useRef(null);
    const panelId = useId();
    const unseen = model.updateIds.filter((id) => !seen.has(id));

    // Updates visible while the disclosure is open are acknowledged too. Keep
    // their row markers until it closes; repeated screenshots add no new IDs.
    useEffect(() => {
        if (!open) return;
        const additions = model.updateIds.filter((id) => !seen.has(id));
        if (!additions.length) return;
        const next = new Set([...seen, ...additions]);
        setSeen(next);
        setOpeningUpdates((previous) => new Set([...previous, ...additions]));
        try { localStorage.setItem(storageKey, JSON.stringify([...next])); } catch { /* Storage may be disabled. */ }
    }, [open, model.updateIds, seen, storageKey]);

    useEffect(() => {
        if (!open) return;
        panel.current?.querySelector('button')?.focus();
    }, [open]);

    return <div className={styles.container} ref={container} onBlur={(event) => {
        if (event.relatedTarget && !container.current?.contains(event.relatedTarget)
            && !panel.current?.contains(event.relatedTarget)) setOpen(false);
    }}>
        <button ref={trigger} className={styles.trigger} aria-expanded={open} aria-controls={panelId}
            onClick={() => {
                if (!open) setOpeningUpdates(new Set(unseen));
                setOpen(!open);
            }}>
            Details {!open && unseen.length > 0 && <span className={styles.badge}>{unseen.length} new</span>}
            <i className="bi bi-chevron-down" aria-hidden="true" />
        </button>
        {open && <Popover anchorRef={trigger} onClose={() => setOpen(false)} align="end"
            width={360} maxHeight={640} className={styles.popover}>
            <section id={panelId} ref={panel} aria-label="Conversation details">
            <div className={styles.heading}>Conversation workspace</div>
            <ResourceList rows={model.rows} seen={seen} openingUpdates={openingUpdates}
                onSelect={(row) => { setOpen(false); onSelect(row); }} />
            <AdvancedStats model={model} />
            </section>
        </Popover>}
    </div>;
}
