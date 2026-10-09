import { useCallback, useEffect, useId, useRef, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import ConfirmButton from '../../components/primitives/ConfirmButton.jsx';
import Popover from '../../components/primitives/Popover.jsx';
import { isGoalOpen, useGoals } from './GoalsState.jsx';
import GoalStatus from './GoalStatus.jsx';
import styles from './GoalPanel.module.css';

function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export default function GoalPanel({ conversationId, isOffline = false, onEdit }) {
    const { goalsByConversation, detailsByConversation, loadGoal, mutateGoal, error: refreshError } = useGoals();
    const goal = goalsByConversation[conversationId];
    const detail = detailsByConversation[conversationId];
    const [expanded, setExpanded] = useState(false);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const anchorRef = useRef(null);
    const triggerRef = useRef(null);
    const detailsRef = useRef(null);
    const detailsId = useId();
    const closeDetails = useCallback(() => setExpanded(false), []);

    useEffect(() => {
        let active = true;
        void loadGoal(conversationId).catch((failure) => { if (active) setError(failure.message); });
        return () => { active = false; };
    }, [conversationId, loadGoal]);
    useEffect(() => {
        if (expanded && goal && detail?.goal?.revision !== goal.revision) {
            void loadGoal(conversationId).catch((failure) => setError(failure.message));
        }
    }, [expanded, goal?.revision, conversationId, loadGoal]);
    useEffect(() => {
        if (!expanded) return;
        // The shared popover is initially hidden while it measures its anchor.
        const frame = requestAnimationFrame(() => detailsRef.current?.focus());
        // Consume Escape before the expanded composer or workspace handles it.
        const escape = (event) => {
            if (event.key !== 'Escape') return;
            event.preventDefault();
            event.stopPropagation();
            setExpanded(false);
            triggerRef.current?.focus();
        };
        document.addEventListener('keydown', escape, true);
        return () => {
            cancelAnimationFrame(frame);
            document.removeEventListener('keydown', escape, true);
        };
    }, [expanded]);

    const act = async (action) => {
        setBusy(action);
        setError('');
        try {
            await mutateGoal(conversationId, action, { goal_id: goal.id });
        } catch (failure) {
            setError(failure.status === 409 ? 'The goal changed. Review its latest state and try again.' : failure.message);
        } finally {
            setBusy('');
        }
    };
    const edit = () => {
        closeDetails();
        onEdit();
    };
    const open = isGoalOpen(goal);
    const completedSteps = (goal?.plan || []).filter((item) => item.status === 'done').length;
    const history = (detail?.history || []).filter((item) => item.id !== goal?.id);
    const summary = goal?.status === 'needs_input' ? 'Reply below to continue'
        : goal?.status === 'scheduled' && goal.resume_at ? `Back ${formatTime(goal.resume_at)}`
        : goal?.status === 'paused' ? 'Nothing happens until you resume'
        : goal?.outcome || goal?.status_reason || goal?.next_action || goal?.objective;

    if (!goal) return null;

    return (
        <section className={styles.panel} aria-label="Conversation goal" data-testid="goal-panel">
            <div className={styles.strip} ref={anchorRef}>
                <button ref={triggerRef} className={styles.summaryButton} onClick={() => setExpanded((current) => !current)} aria-expanded={expanded} aria-controls={expanded ? detailsId : undefined}>
                    <GoalStatus goal={goal} />
                    <span className={styles.summary} title={summary}>{summary}</span>
                    <i className={`bi ${expanded ? 'bi-chevron-down' : 'bi-chevron-up'}`} aria-hidden="true" />
                </button>
                {open && <Button variant="ghost" disabled={Boolean(busy) || isOffline} loading={busy === 'pause' || busy === 'resume'} loadingLabel="Updating…" onClick={() => act(goal.status === 'paused' ? 'resume' : 'pause')}>
                    <i className={`bi ${goal.status === 'paused' ? 'bi-play' : 'bi-pause'}`} aria-hidden="true" />
                    {goal.status === 'paused' ? 'Resume' : 'Pause'}
                </Button>}
            </div>
            {goal.status === 'needs_input' && <div className={styles.question} role="group" aria-label="Question about your goal">{goal.status_reason || goal.next_action || 'Reply in this chat when you are ready.'}</div>}
            {(error || refreshError) && <div className={styles.feedback}><Callout tone="warning" title={error || refreshError} onDismiss={error ? () => setError('') : undefined} /></div>}
            {expanded && <Popover anchorRef={anchorRef} returnFocusRef={triggerRef} onClose={closeDetails} className={styles.popover} role="region" ariaLabel="Goal details" testId="goal-details">
                <div ref={detailsRef} tabIndex={-1} className={styles.details} id={detailsId} onBlur={(event) => {
                    if (event.relatedTarget && !event.currentTarget.contains(event.relatedTarget) && !anchorRef.current?.contains(event.relatedTarget)) closeDetails();
                }}>
                    <div>
                        <p className={styles.fullObjective}>{goal.objective}</p>
                        {goal.status_reason && goal.status !== 'needs_input' && <p className={styles.description}>{goal.status_reason}</p>}
                        <p className={styles.description}>{goal.kind === 'ongoing' ? 'Ongoing goal' : 'One-time goal'}{goal.plan?.length ? ` · ${completedSteps} of ${goal.plan.length} steps done` : ''}</p>
                    </div>
                    <div className={styles.detailGrid}>
                        <section>
                            <h3>Steps</h3>
                            {goal.plan?.length ? <ol className={styles.plan}>{goal.plan.map((item) => <li key={item.id} className={styles.planItem}>
                                <i className={`bi ${item.status === 'done' ? 'bi-check2' : item.status === 'in_progress' ? 'bi-arrow-repeat' : item.status === 'blocked' ? 'bi-exclamation-circle' : item.status === 'skipped' ? 'bi-dash-circle' : 'bi-circle'}`} aria-hidden="true" />
                                <div><span>{item.title}</span><span className={styles.stepStatus}>{item.status.replace('_', ' ')}</span>{item.notes && <p className={styles.description}>{item.notes}</p>}</div>
                            </li>)}</ol> : <p className={styles.description}>The agent will build its plan as it works.</p>}
                        </section>
                        <div className={styles.detailColumn}>
                            {goal.next_action && <section><h3>Next up</h3><p className={styles.prose}>{goal.next_action}</p></section>}
                            {goal.constraints && <section><h3>Limits and preferences</h3><p className={styles.prose}>{goal.constraints}</p></section>}
                            {goal.success_criteria?.length > 0 && <section><h3>Done when</h3><ul className={styles.criteria}>{goal.success_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul></section>}
                            {goal.outcome && <section><h3>Outcome</h3><p className={styles.prose}>{goal.outcome}</p></section>}
                        </div>
                    </div>
                    {goal.progress?.length > 0 && <details><summary className={styles.disclosure}>Progress updates</summary><ol className={styles.progress}>{[...goal.progress].reverse().map((entry) => <li key={entry.id}><time dateTime={entry.created_at}>{formatTime(entry.created_at)}</time><p>{entry.summary}</p>{entry.next_action && <p className={styles.description}>Next: {entry.next_action}</p>}</li>)}</ol></details>}
                    {history.length > 0 && <details><summary className={styles.disclosure}>Previous goals ({history.length})</summary><ul className={styles.history}>{history.map((item) => <li key={item.id}><GoalStatus goal={item} /><span>{item.objective}</span>{item.outcome && <p className={styles.description}>{item.outcome}</p>}</li>)}</ul></details>}
                    <div className={styles.actions}>
                        {open ? <>
                            <Button variant="ghost" onClick={edit} disabled={isOffline || Boolean(busy)}><i className="bi bi-pencil" aria-hidden="true" /> Change goal</Button>
                            {['scheduled', 'needs_input'].includes(goal.status) && <Button variant="ghost" disabled={isOffline || Boolean(busy)} onClick={() => act('resume')}>Resume now</Button>}
                            <ConfirmButton label="Cancel goal" confirmLabel="Cancel this goal?" onConfirm={() => act('cancel')} disabled={isOffline || Boolean(busy)} />
                        </> : <Button variant="ghost" onClick={edit} disabled={isOffline}><i className="bi bi-plus" aria-hidden="true" /> Start another goal</Button>}
                    </div>
                </div>
            </Popover>}
        </section>
    );
}
