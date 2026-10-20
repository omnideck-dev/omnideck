import { useId, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import IconButton from '../../components/primitives/IconButton.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import Select from '../../components/primitives/Select.jsx';
import styles from './GoalPanel.module.css';

const PLAN_STATUSES = [
    { value: 'pending', label: 'Pending' },
    { value: 'in_progress', label: 'In progress' },
    { value: 'done', label: 'Done' },
    { value: 'blocked', label: 'Blocked' },
    { value: 'skipped', label: 'Skipped' },
];

function draftFromGoal(goal) {
    return {
        objective: goal?.objective || '',
        kind: goal?.kind || 'finite',
        plan: (goal?.plan || []).map((item) => ({ ...item })),
        revision: goal?.revision,
    };
}

export default function GoalEditor({ goal, latestGoal, initialObjective = '', onSave, onReload, onClose }) {
    const headingId = useId();
    const [draft, setDraft] = useState(() => draftFromGoal(goal || { objective: initialObjective }));
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [conflict, setConflict] = useState(false);
    const change = (key, value) => setDraft((current) => ({ ...current, [key]: value }));
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
        if (draft.plan.some((item) => !item.title.trim())) { setError('Give each plan step a title.'); return; }
        setSaving(true);
        setError('');
        try {
            await onSave({
                objective: draft.objective.trim(),
                ...(goal ? { expected_revision: draft.revision, plan: draft.plan } : { kind: draft.kind }),
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
                    <h2 id={headingId}>{goal ? 'Edit goal' : 'Assign a goal'}</h2>
                    <p className={styles.description}>The agent manages its plan and continues in this chat. You can pause or cancel at any time.</p>
                </div>
                <div className={styles.editorBody}>
                    {error && <Callout tone="danger" title="Could not save goal" description={error} />}
                    {conflict && <Button variant="ghost" disabled={saving} onClick={reload}>Load latest version</Button>}
                    <label className={styles.field}>
                        <span>What would you like done?</span>
                        <textarea className={styles.textarea} value={draft.objective} onChange={(event) => change('objective', event.target.value)} placeholder="Describe the goal, including any preferences or limits" required disabled={saving} />
                    </label>
                    {!goal && <div className={styles.field}>
                        <span id={`${headingId}-kind`}>Goal type</span>
                        <Select ariaLabelledBy={`${headingId}-kind`} value={draft.kind} onChange={(value) => change('kind', value)} disabled={saving} options={[
                            { value: 'finite', label: 'One-time' },
                            { value: 'ongoing', label: 'Ongoing' },
                        ]} />
                        <p className={styles.description}>{draft.kind === 'ongoing' ? 'Continues until you pause or cancel it.' : 'Completes when the outcome is achieved.'}</p>
                    </div>}
                    {goal && <section className={styles.fields} aria-label="Edit plan">
                        <h3>Plan</h3>
                        {draft.plan.map((item, index) => <div className={styles.planEditor} key={item.id}>
                            <div className={styles.planEditorRow}>
                                <input className={styles.input} aria-label={`Step ${index + 1} title`} value={item.title} onChange={(event) => changeItem(item.id, { title: event.target.value })} disabled={saving} />
                                <Select ariaLabel={`Step ${index + 1} status`} options={PLAN_STATUSES} value={item.status} onChange={(value) => changeItem(item.id, { status: value })} disabled={saving} />
                                <IconButton aria-label={`Remove step ${index + 1}`} disabled={saving} onClick={() => setDraft((current) => ({ ...current, plan: current.plan.filter((step) => step.id !== item.id).map((step) => ({ ...step, depends_on: (step.depends_on || []).filter((id) => id !== item.id) })) }))}><i className="bi bi-trash3" aria-hidden="true" /></IconButton>
                            </div>
                            <input className={styles.input} aria-label={`Step ${index + 1} notes`} value={item.notes || ''} placeholder="Notes" onChange={(event) => changeItem(item.id, { notes: event.target.value })} disabled={saving} />
                        </div>)}
                        <div><Button variant="ghost" disabled={saving} onClick={() => change('plan', [...draft.plan, { id: crypto.randomUUID(), title: '', status: 'pending', notes: '', depends_on: [] }])}><i className="bi bi-plus" aria-hidden="true" /> Add step</Button></div>
                    </section>}
                </div>
                <div className={styles.editorFooter}>
                    <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
                    <Button variant="filled" type="submit" loading={saving} loadingLabel="Saving…" disabled={conflict}>{goal ? 'Save changes' : 'Start goal'}</Button>
                </div>
            </form>
        </Modal>
    );
}
