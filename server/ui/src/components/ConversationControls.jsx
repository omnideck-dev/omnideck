import { useCallback, useEffect, useId, useRef, useState } from 'react';
import ContextMeter, { contextMeterState } from './ContextMeter.jsx';
import IconButton from './primitives/IconButton.jsx';
import Popover from './primitives/Popover.jsx';
import styles from './ConversationControls.module.css';

export default function ConversationControls({ anchorRef, agentName, turnCount, contextUsage, onOpenArtifacts, onOpenNetwork, networkAgentCount, networkRunningCount }) {
    const context = contextUsage?.context_limit ? contextMeterState(contextUsage) : null;
    const [expanded, setExpanded] = useState(false);
    const triggerRef = useRef(null);
    const detailsRef = useRef(null);
    const detailsId = useId();
    const close = useCallback(() => setExpanded(false), []);
    useEffect(() => {
        if (!expanded) return;
        const frame = requestAnimationFrame(() => detailsRef.current?.focus());
        const escape = (event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            close();
            triggerRef.current?.querySelector('button')?.focus();
        };
        document.addEventListener('keydown', escape, true);
        return () => {
            cancelAnimationFrame(frame);
            document.removeEventListener('keydown', escape, true);
        };
    }, [expanded, close]);
    return <div className={styles.controls}>
        {networkAgentCount > 0 && <button type="button" className={styles.agentsButton}
            aria-label={`Open sub-agents (${networkAgentCount}${networkRunningCount ? `, ${networkRunningCount} running` : ''})`}
            title="Sub-agents" data-testid="network-indicator" onClick={onOpenNetwork}>
            <i className={`bi bi-diagram-3 ${networkRunningCount > 0 ? styles.running : ''}`} aria-hidden="true" />
            {networkAgentCount}
        </button>}
        <IconButton aria-label="Artifacts in this chat" title="Artifacts in this chat" data-testid="conversation-artifacts-trigger" onClick={onOpenArtifacts}>
            <i className="bi bi-collection" aria-hidden="true" />
        </IconButton>
        <span ref={triggerRef} className={styles.detailsTrigger}>
            <IconButton aria-label="Conversation details" title="Conversation details" aria-expanded={expanded} aria-controls={expanded ? detailsId : undefined} onClick={() => setExpanded((value) => !value)}><i className="bi bi-info-circle" aria-hidden="true" /></IconButton>
        </span>
        {expanded && <Popover anchorRef={anchorRef} triggerRef={triggerRef} returnFocusRef={triggerRef} onClose={close} placement="bottom" align="end" maxWidth={420} maxHeight={360} className={styles.popover} role="region" ariaLabel="Conversation details">
            <div ref={detailsRef} tabIndex={-1} id={detailsId} className={styles.details}>
                <div className={styles.heading}><h3>Conversation details</h3><IconButton aria-label="Close conversation details" onClick={() => { close(); triggerRef.current?.querySelector('button')?.focus(); }}><i className="bi bi-x-lg" aria-hidden="true" /></IconButton></div>
                <p className={styles.metadata}><span data-testid="chat-agent">Agent: {agentName}</span>{turnCount > 0 && <span data-testid="chat-turns">{turnCount} turn{turnCount === 1 ? '' : 's'}</span>}</p>
                {context
                    ? <><div className={styles.context}>Context <ContextMeter contextUsage={contextUsage} /></div><p className={styles.explanation}>At {Math.round(context.threshold * 100)}%, older messages are summarized to make room for continued work.</p></>
                    : <p className={styles.explanation}>Context shows after the agent's first reply.</p>}
            </div>
        </Popover>}
    </div>;
}
