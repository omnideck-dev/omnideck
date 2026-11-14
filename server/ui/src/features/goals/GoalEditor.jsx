import { useId, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import styles from './GoalPanel.module.css';

const STEP_STATES = { in_progress: 'Now', done: 'Done', blocked: 'Blocked', skipped: 'Skipped' };

function draftFromGoal(goal, objective = '') {
    return {
        objective: objective || goal?.objective || '',
        plan: (goal?.plan || []).map((item) => ({ ...item })),
        revision: goal?.revision,
    };
}

function PlanStepEditor({ item, index, titles, saving, invalid, onChange, onRemove }) {
    const [open, setOpen] = useState(!item.title);
    return <details className={styles.planEditor} open={open || invalid} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary className={styles.stepSummary}>
            <span className={styles.stepNumber}>{index + 1}.</span>
            <span className={styles.stepTitle}>{item.title || 'New step'}</span>
            {STEP_STATES[item.status] && <span className={styles.stepState}>{STEP_STATES[item.status]}</span>}
        </summary>
        {item.depends_on?.length > 0 && <p className={styles.dependsOn}>Depends on: {item.depends_on.map((id) => titles[id] || id).join(', ')}</p>}
        <div className={styles.stepFields}>
            <label className={styles.field}><span>Step</span><textarea className={styles.textarea} aria-label={`Step ${index + 1} title`} rows={2} value={item.title} onChange={(event) => onChange({ title: event.target.value })} disabled={saving} /></label>
            <label className={styles.field}><span>Notes</span><textarea className={styles.textarea} aria-label={`Step ${index + 1} notes`} rows={3} value={item.notes || ''} placeholder="Add details for this step" onChange={(event) => onChange({ notes: event.target.value })} disabled={saving} /></label>
            <div className={styles.planEditorRow}>
                <Button variant="ghost" aria-label={`Remove step ${index + 1}`} disabled={saving} onClick={onRemove}><i className="bi bi-trash3" aria-hidden="true" /> Remove step</Button>
            </div>
        </div>
    </details>;
}

export default function GoalEditor({ goal, latestGoal, initialObjective = '', onSave, onReload, onClose }) {
    const headingId = useId();
    // Text typed after /goal replaces the objective of an open goal instead of being lost.
    const replacing = Boolean(goal && initialObjective.trim() && initialObjective.trim() !== goal.objective);
    const [draft, setDraft] = useState(() => draftFromGoal(goal, initialObjective.trim()));
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [conflict, setConflict] = useState(false);
    const [planOpen, setPlanOpen] = useState(false);
    const [validatePlan, setValidatePlan] = useState(false);
    const change = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
    const titles = Object.fromEntries(draft.plan.map((item) => [item.id, item.title]));
    const changeItem = (id, changes) => setDraft((current) => ({ ...current, plan: current.plan.map((item) => item.id === id ? { ...item, ...changes } : item) }));

    const reload = async () => {
        setSaving(true);
        try {
            setDraft(draftFromGoal(onReload ? await onReload() : latestGoal || goal));
            setConflict(false);
            setError('');
        } catch (failure) {
            setError(failure.message);
        } finally {
            setSaving(false);
        }
    };

    const submit = async (event) => {
        event.preventDefault();
        if (!draft.objective.trim()) { setError('Describe what you want to achieve.'); return; }
        if (draft.plan.some((item) => !item.title.trim())) { setPlanOpen(true); setValidatePlan(true); setError('Give each plan step a title.'); return; }
        setSaving(true);
        setError('');
        try {
            await onSave({
                objective: draft.objective.trim(),
                ...(goal ? { expected_revision: draft.revision, plan: draft.plan } : {}),
            });
            onClose();
        } catch (failure) {
            setConflict(failure.status === 409);
            setError(failure.status === 409
                ? 'This chat’s goal changed while you were editing. Your changes are still here. Load the latest version before saving.'
                : failure.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <Modal onClose={saving ? undefined : onClose} labelledBy={headingId} layout="contained" width="min(100%, 640px)">
            <form className={styles.editor} onSubmit={submit}>
                <div className={styles.editorHeader}>
                    <div className={styles.editorHeading}><h2 id={headingId}>{goal ? 'Edit' : 'Start a goal'}</h2><IconButton aria-label="Close goal editor" disabled={saving} onClick={onClose}><i className="bi bi-x-lg" aria-hidden="true" /></IconButton></div>
                    <p className={styles.description}>{goal ? 'Change what you want done or the steps of the agent’s plan.' : 'The agent works on this in this chat. It can ask you questions and come back later on its own. You can pause it at any time.'}</p>
                </div>
                <div className={styles.editorBody}>
                    {error && <Callout tone="danger" title="Could not save goal" description={error} />}
                    {conflict && <Button variant="ghost" disabled={saving} onClick={reload}>Load latest version</Button>}
                    {replacing && <p className={styles.editorNote}>This replaces the current objective.</p>}
                    <label className={styles.field}>
                        <span>What would you like done?</span>
                        <textarea className={styles.textarea} value={draft.objective} onChange={(event) => change('objective', event.target.value)} placeholder="Say what done looks like and any limits, such as a budget or people to avoid contacting." required disabled={saving} />
                    </label>
                    {goal && <details className={styles.planDisclosure} open={planOpen} onToggle={(event) => setPlanOpen(event.currentTarget.open)}>
                        <summary className={styles.disclosure}>Plan <span>{draft.plan.length} {draft.plan.length === 1 ? 'step' : 'steps'}</span></summary>
                        <section className={styles.planFields} aria-label="Edit plan">
                        {draft.plan.map((item, index) => <PlanStepEditor key={item.id} item={item} index={index} titles={titles} saving={saving} invalid={validatePlan && !item.title.trim()} onChange={(changes) => changeItem(item.id, changes)} onRemove={() => setDraft((current) => ({ ...current, plan: current.plan.filter((step) => step.id !== item.id).map((step) => ({ ...step, depends_on: (step.depends_on || []).filter((id) => id !== item.id) })) }))} />)}
                        <div><Button variant="ghost" disabled={saving} onClick={() => change('plan', [...draft.plan, { id: crypto.randomUUID(), title: '', status: 'pending', notes: '', depends_on: [] }])}><i className="bi bi-plus" aria-hidden="true" /> Add step</Button></div>
                        </section>
                    </details>}
                </div>
                <div className={styles.editorFooter}>
                    <div className={styles.editorFooterRow}>
                        <div className={styles.actions}>
                            <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
                            <Button variant="filled" type="submit" loading={saving} loadingLabel="Saving…" disabled={conflict}>{goal ? 'Save changes' : 'Start goal'}</Button>
                        </div>
                        {goal && (latestGoal || goal).running && <p className={styles.editorNote}>The agent sees your changes on its next step.</p>}
                    </div>
                </div>
            </form>
        </Modal>
    );
}
