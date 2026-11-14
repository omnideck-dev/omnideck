import { useEffect, useRef, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import ConfirmButton from '../../components/primitives/ConfirmButton.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import Popover from '../../components/primitives/Popover.jsx';
import { goalStatus, isGoalOpen, nextUpStep, reasonLine } from './goalStatus.js';
import { useGoals } from './GoalsState.jsx';
import GoalStatus from './GoalStatus.jsx';
import GoalHistory from './GoalHistory.jsx';
import GoalReopenDialog from './GoalReopenDialog.jsx';
import styles from './GoalPanel.module.css';

const STEP_ICONS = {
    done: 'bi-check-circle',
    skipped: 'bi-dash-circle',
    in_progress: 'bi-record-circle',
    blocked: 'bi-exclamation-circle',
    pending: 'bi-circle',
};

function stepTitles(plan) {
    return Object.fromEntries(plan.map((step) => [step.id, step.title]));
}

export function GoalPlan({ plan }) {
    if (!plan.length) return <p className={styles.description}>The agent will build its plan as it works.</p>;
    const finished = plan.filter((step) => ['done', 'skipped'].includes(step.status)).length;
    const titles = stepTitles(plan);
    return <section className={styles.block} aria-label="Plan">
        <div className={styles.progressRow}>
            <h3 className={styles.label}>Plan</h3>
            <span className={styles.bar} role="progressbar" aria-label="Plan progress" aria-valuemin={0} aria-valuemax={plan.length} aria-valuenow={finished}>
                <span className={styles.barFill} style={{ width: `${Math.round((finished / plan.length) * 100)}%` }} />
            </span>
            <span className={styles.progressCount}>{finished} of {plan.length}</span>
        </div>
        <ol className={styles.plan}>{plan.map((step) => <li key={step.id} className={`${styles.planItem} ${styles[step.status] || ''}`}>
            <i className={`bi ${STEP_ICONS[step.status] || 'bi-circle'}`} aria-hidden="true" />
            <div>
                <span>{step.title}</span>
                {step.status === 'in_progress' && <span className={styles.nowTag}>Now</span>}
                {step.status === 'blocked' && <span className={styles.stepState}>Blocked</span>}
                {step.status === 'skipped' && <span className={styles.stepState}>Skipped</span>}
                {step.depends_on?.length > 0 && <span className={styles.stepNote}>Depends on: {step.depends_on.map((id) => titles[id] || id).join(', ')}</span>}
                {step.notes && <span className={styles.stepNote}>{step.notes}</span>}
            </div>
        </li>)}</ol>
    </section>;
}

function MoreActions({ ended, disabled, onOpenHistory, onCancel }) {
    const [open, setOpen] = useState(false);
    const anchorRef = useRef(null);
    const contentRef = useRef(null);
    const trigger = () => anchorRef.current?.querySelector('button');
    const close = () => { setOpen(false); trigger()?.focus(); };
    const focusFirst = () => contentRef.current?.querySelector('[role="menuitem"]:not(:disabled)')?.focus();
    const handleKeyDown = (event) => {
        if (event.key === 'Escape') { event.preventDefault(); close(); return; }
        if (event.key === 'Tab') { setOpen(false); return; }
        if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const items = Array.from(contentRef.current.querySelectorAll('[role="menuitem"]:not(:disabled)'));
        const current = items.indexOf(document.activeElement);
        const next = { ArrowDown: (current + 1) % items.length, ArrowUp: (current - 1 + items.length) % items.length, Home: 0, End: items.length - 1 }[event.key];
        items[next]?.focus();
    };
    return <>
        <span ref={anchorRef}>
            <IconButton size="md" aria-label="More goal actions" aria-haspopup="menu" aria-expanded={open} disabled={disabled}
                onClick={() => setOpen((value) => !value)}><i className="bi bi-three-dots" aria-hidden="true" /></IconButton>
        </span>
        {open && <Popover anchorRef={anchorRef} returnFocusRef={{ current: trigger() }} onClose={close} onOpen={focusFirst}
            width={200} align="end" role="menu" ariaLabel="Goal actions" className={styles.menu}>
            <div className={styles.menuItems} ref={contentRef} onKeyDown={handleKeyDown}>
                <Button variant="menuItem" role="menuitem" tabIndex={-1} onClick={() => { close(); onOpenHistory(); }}>
                    <i className="bi bi-clock-history" aria-hidden="true" /> Open goal history
                </Button>
                {!ended && <>
                    <div role="separator" className={styles.menuSeparator} />
                    <ConfirmButton appearance="menuItem" role="menuitem" tabIndex={-1} label="Cancel goal…" aria-label="Cancel goal"
                        confirmLabel="Cancel this goal?" busyLabel="Cancelling…" icon="bi-x-circle"
                        onConfirm={async () => { await onCancel(); setOpen(false); }} />
                </>}
            </div>
        </Popover>}
    </>;
}

export default function GoalPanel({ conversationId, isOffline = false, onEdit, onStartGoal, onOpenChat }) {
    const { goalsByConversation, detailsByConversation, loadGoal, mutateGoal, error: refreshError } = useGoals();
    const goal = goalsByConversation[conversationId];
    const detail = detailsByConversation[conversationId];
    const [loaded, setLoaded] = useState(false);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const [historyOpen, setHistoryOpen] = useState(false);
    const [reopening, setReopening] = useState(false);
    const historyRef = useRef(null);

    useEffect(() => {
        let active = true;
        void loadGoal(conversationId).catch((failure) => { if (active) setError(failure.message); }).finally(() => { if (active) setLoaded(true); });
        return () => { active = false; };
    }, [conversationId, loadGoal]);
    useEffect(() => {
        if (loaded && goal && detail?.goal?.revision !== goal.revision) {
            void loadGoal(conversationId).catch((failure) => setError(failure.message));
        }
    }, [loaded, goal?.revision, conversationId, loadGoal]);
    useEffect(() => {
        if (historyOpen) historyRef.current?.scrollIntoView?.({ block: 'nearest' });
    }, [historyOpen]);

    const act = async (action, body = {}) => {
        setBusy(action);
        setError('');
        try {
            await mutateGoal(conversationId, action, { goal_id: goal.id, ...body });
        } catch (failure) {
            setError(failure.status === 409 ? `${failure.message} Review the goal's latest state and try again.` : failure.message);
            throw failure;
        } finally {
            setBusy('');
        }
    };
    const run = (action) => { void act(action).catch(() => {}); };
    const openChat = onOpenChat && <Button variant="ghost" onClick={onOpenChat}><i className="bi bi-chat-left-text" aria-hidden="true" /> Open chat</Button>;

    if (!goal) return <section className={styles.goalView} aria-label="Goal details" data-testid="goal-details"><div className={styles.details}>
        {openChat && <div className={styles.viewToolbar}>{openChat}</div>}
        {error ? <Callout tone="warning" title="Could not load this goal" description={error} />
            : !loaded ? <p role="status">Loading goal…</p>
                : <div className={styles.empty}>
                    <i className={`bi bi-bullseye ${styles.emptyIcon}`} aria-hidden="true" />
                    <h3 className={styles.emptyTitle}>This chat has no goal</h3>
                    <p className={styles.description}>A goal is a task the agent keeps working on in this chat. It keeps a plan, can ask you questions, and can come back later on its own.</p>
                    <Button variant="filled" onClick={onStartGoal} disabled={isOffline}><i className="bi bi-bullseye" aria-hidden="true" /> Start a goal…</Button>
                </div>}
    </div></section>;

    const open = isGoalOpen(goal);
    const status = goalStatus(goal);
    const reason = reasonLine(goal);
    const disabled = isOffline || Boolean(busy);
    const futureWake = goal.next?.kind === 'wake' && Date.parse(goal.next.at) > Date.now();
    const showRunNow = open && !goal.paused && !goal.running && futureWake;
    const showRetry = open && !goal.paused && !goal.running && goal.next?.kind === 'error';
    const nextUp = !goal.running ? nextUpStep(goal) : '';
    const history = (detail?.history || []).filter((item) => item.id !== goal.id);

    return (
        <section className={styles.goalView} aria-label="Goal details" data-testid="goal-details">
            <div className={styles.details}>
                {openChat && <div className={styles.viewToolbar}>{openChat}</div>}
                <div className={styles.block}>
                    <GoalStatus goal={goal} className={styles.statusLine} />
                    <p className={styles.objective}>{goal.objective}</p>
                    {reason && <p className={styles.statusReason} data-testid="goal-reason">{reason}</p>}
                </div>
                {(error || refreshError) && <Callout tone="warning" title={error || refreshError} onDismiss={error ? () => setError('') : undefined} />}
                <div className={styles.actions}>
                    {open ? <>
                        {goal.paused
                            ? <Button variant="filled" disabled={disabled} loading={busy === 'resume'} loadingLabel="Resuming…" onClick={() => run('resume')}>
                                <i className="bi bi-play" aria-hidden="true" /> Resume
                            </Button>
                            : <Button variant="outline" disabled={disabled} loading={busy === 'pause'} loadingLabel="Pausing…" onClick={() => run('pause')}>
                                <i className="bi bi-pause" aria-hidden="true" /> Pause
                            </Button>}
                        {showRunNow && <Button variant="ghost" disabled={disabled} loading={busy === 'run'} loadingLabel="Starting…" onClick={() => run('run')}>
                            <i className="bi bi-play-circle" aria-hidden="true" /> Run now
                        </Button>}
                        <Button variant="ghost" onClick={onEdit} disabled={disabled}><i className="bi bi-pencil" aria-hidden="true" /> Edit</Button>
                    </> : <>
                        <Button variant="filled" onClick={() => setReopening(true)} disabled={disabled}><i className="bi bi-arrow-counterclockwise" aria-hidden="true" /> Reopen…</Button>
                        <Button variant="ghost" onClick={onStartGoal} disabled={disabled}><i className="bi bi-bullseye" aria-hidden="true" /> Start a new goal…</Button>
                    </>}
                    <span className={styles.spacer} />
                    <MoreActions ended={!open} disabled={isOffline} onOpenHistory={() => setHistoryOpen(true)} onCancel={() => act('cancel')} />
                </div>

                {showRetry && <div data-testid="goal-error"><Callout tone="danger" title={goal.next.message}
                    description={<Button variant="filled" className={styles.calloutButton} disabled={disabled} loading={busy === 'run'} loadingLabel="Retrying…" onClick={() => run('run')}>
                        <i className="bi bi-play" aria-hidden="true" /> Retry
                    </Button>} /></div>}
                {status.key === 'done' && <div data-testid="goal-outcome"><Callout tone="success" title="Outcome" description={goal.next.outcome} /></div>}
                {nextUp && <section className={styles.block} aria-label="Next up">
                    <h3 className={styles.label}>Next up</h3>
                    <p className={styles.prose}>{nextUp}</p>
                </section>}
                <GoalPlan plan={goal.plan || []} />
                {goal.summary && <section className={styles.block} aria-label="What the agent knows">
                    <h3 className={styles.label}>What the agent knows</h3>
                    <p className={styles.prose}>{goal.summary}</p>
                </section>}
                <div className={styles.sections} ref={historyRef}>
                    <GoalHistory key={goal.id} conversationId={conversationId} goalId={goal.id} revision={goal.revision}
                        open={historyOpen} onOpenChange={setHistoryOpen} />
                    {history.length > 0 && <details><summary className={styles.disclosure}>Previous goals<span className={styles.sectionMeta}>{history.length}</span></summary>
                        <ul className={styles.history}>{history.map((item) => <li key={item.id}>
                            <GoalStatus goal={item} compact />
                            <span>{item.objective}</span>
                            {item.next?.kind === 'done' && <p className={styles.description}>{item.next.outcome}</p>}
                        </li>)}</ul>
                    </details>}
                </div>
            </div>
            {reopening && <GoalReopenDialog onClose={() => setReopening(false)}
                onSubmit={(text) => act('reopen', { text, profile_id: goal.profile_id })} />}
        </section>
    );
}
