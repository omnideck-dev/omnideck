import { useEffect, useId, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import ConfirmButton from '../../components/primitives/ConfirmButton.jsx';
import { useConversationCatalog } from '../conversation/catalog/ConversationCatalog.jsx';
import { isGoalOpen, useGoals } from './GoalsState.jsx';
import GoalEditor from './GoalEditor.jsx';
import GoalStatus from './GoalStatus.jsx';
import styles from './GoalPanel.module.css';

function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export default function GoalPanel({ conversationId, profileId, isOffline = false }) {
    const { goalsByConversation, detailsByConversation, loadGoal, mutateGoal, error: refreshError } = useGoals();
    const { refetch: refreshConversations } = useConversationCatalog();
    const goal = goalsByConversation[conversationId];
    const detail = detailsByConversation[conversationId];
    const [expanded, setExpanded] = useState(false);
    const [editing, setEditing] = useState(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState('');
    const detailsId = useId();

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
    const save = async (body) => {
        await mutateGoal(conversationId, editing === 'create' ? 'create' : 'edit', { ...body, ...(editing === 'create' ? { profile_id: profileId } : {}) });
        if (editing === 'create') void refreshConversations();
        setExpanded(true);
    };
    const open = isGoalOpen(goal);
    const completedSteps = (goal?.plan || []).filter((item) => item.status === 'done').length;
    const history = (detail?.history || []).filter((item) => item.id !== goal?.id);

    return (
        <section className={styles.panel} aria-label="Conversation goal" data-testid="goal-panel">
            <div className={styles.strip}>
                {goal ? <>
                    <button className={styles.summaryButton} onClick={() => setExpanded((current) => !current)} aria-expanded={expanded} aria-controls={detailsId}>
                        <i className="bi bi-bullseye" aria-hidden="true" />
                        <span className={styles.objective} title={goal.objective}>{goal.objective}</span>
                        <GoalStatus goal={goal} />
                        <i className={`bi ${expanded ? 'bi-chevron-up' : 'bi-chevron-down'}`} aria-hidden="true" />
                    </button>
                    {open && <Button variant="ghost" disabled={Boolean(busy) || isOffline} loading={busy === 'pause' || busy === 'resume'} loadingLabel="Updating…" onClick={() => act(goal.status === 'paused' || goal.status === 'needs_input' || goal.status === 'scheduled' ? 'resume' : 'pause')}>
                        {goal.status === 'paused' ? 'Resume' : ['needs_input', 'scheduled'].includes(goal.status) ? 'Resume now' : 'Pause'}
                    </Button>}
                </> : <>
                    <span className={styles.emptyLabel}><i className="bi bi-bullseye" aria-hidden="true" /> Give this chat a goal</span>
                    <Button variant="ghost" disabled={isOffline} onClick={() => setEditing('create')}>Assign goal</Button>
                </>}
            </div>
            {goal?.status === 'scheduled' && goal.resume_at && <div className={styles.nextWake}>Resumes {formatTime(goal.resume_at)}{goal.wake_reason ? ` · ${goal.wake_reason}` : ''}</div>}
            {goal?.status === 'needs_input' && <div className={styles.nextWake}>{goal.status_reason || goal.next_action || 'Reply in this chat when you are ready.'}</div>}
            {(error || (goal && refreshError)) && <div className={styles.feedback}><Callout tone="warning" title={error || refreshError} onDismiss={error ? () => setError('') : undefined} /></div>}
            {goal && expanded && <div className={styles.details} id={detailsId}>
                <div className={styles.detailHeading}>
                    <span className={styles.description}>{goal.kind === 'ongoing' ? 'Ongoing goal' : 'Outcome goal'}{goal.plan?.length ? ` · ${completedSteps} of ${goal.plan.length} steps done` : ''}</span>
                    <div className={styles.actions}>
                        {open ? <>
                            <Button variant="ghost" onClick={() => setEditing('edit')} disabled={isOffline || Boolean(busy)}>Edit goal</Button>
                            {['scheduled', 'needs_input'].includes(goal.status) && <Button variant="ghost" disabled={isOffline || Boolean(busy)} onClick={() => act('pause')}>Pause</Button>}
                            <ConfirmButton label="Cancel goal" confirmLabel="Cancel this goal?" onConfirm={() => act('cancel')} disabled={isOffline || Boolean(busy)} />
                        </> : <Button variant="ghost" onClick={() => setEditing('create')} disabled={isOffline}>Assign new goal</Button>}
                    </div>
                </div>
                <p className={styles.fullObjective}>{goal.objective}</p>
                {goal.status_reason && goal.status !== 'needs_input' && <p className={styles.description}>{goal.status_reason}</p>}
                {goal.constraints && <div><h3>Constraints</h3><p className={styles.prose}>{goal.constraints}</p></div>}
                {goal.success_criteria?.length > 0 && <div><h3>Success criteria</h3><ul className={styles.criteria}>{goal.success_criteria.map((criterion, index) => <li key={index}>{criterion}</li>)}</ul></div>}
                {goal.next_action && <div><h3>Next action</h3><p className={styles.prose}>{goal.next_action}</p></div>}
                <div>
                    <h3>Plan</h3>
                    {goal.plan?.length ? <ol className={styles.plan}>{goal.plan.map((item) => <li key={item.id} className={styles.planItem}>
                        <i className={`bi ${item.status === 'done' ? 'bi-check-square' : item.status === 'in_progress' ? 'bi-arrow-repeat' : item.status === 'blocked' ? 'bi-exclamation-circle' : item.status === 'skipped' ? 'bi-dash-square' : 'bi-square'}`} aria-hidden="true" />
                        <div><span>{item.title}</span><span className={styles.stepStatus}>{item.status.replace('_', ' ')}</span>{item.notes && <p className={styles.description}>{item.notes}</p>}</div>
                    </li>)}</ol> : <p className={styles.description}>The agent will build its plan as it works.</p>}
                </div>
                {goal.outcome && <div><h3>Outcome</h3><p className={styles.prose}>{goal.outcome}</p></div>}
                {goal.progress?.length > 0 && <div><h3>Progress</h3><ol className={styles.progress}>{[...goal.progress].reverse().map((entry) => <li key={entry.id}><time dateTime={entry.created_at}>{formatTime(entry.created_at)}</time><p>{entry.summary}</p>{entry.next_action && <p className={styles.description}>Next: {entry.next_action}</p>}</li>)}</ol></div>}
                {history.length > 0 && <details><summary className={styles.disclosure}>Previous goals ({history.length})</summary><ul className={styles.history}>{history.map((item) => <li key={item.id}><GoalStatus goal={item} /><span>{item.objective}</span>{item.outcome && <p className={styles.description}>{item.outcome}</p>}</li>)}</ul></details>}
            </div>}
            {editing && <GoalEditor goal={editing === 'edit' ? goal : null} latestGoal={goal} onSave={save} onClose={() => setEditing(null)} />}
        </section>
    );
}
