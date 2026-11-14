import { useId, useState } from 'react';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import Modal from '../../components/primitives/Modal.jsx';
import styles from './GoalPanel.module.css';

/** Ask what still needs doing. The answer goes into the chat as the user's message. */
export default function GoalReopenDialog({ onSubmit, onClose }) {
    const headingId = useId();
    const [text, setText] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const submit = async (event) => {
        event.preventDefault();
        if (!text.trim()) return;
        setSaving(true);
        setError('');
        try {
            await onSubmit(text.trim());
            onClose();
        } catch (failure) {
            setError(failure.message);
            setSaving(false);
        }
    };
    return <Modal onClose={saving ? undefined : onClose} labelledBy={headingId} width="min(100%, 520px)">
        <form className={styles.fields} onSubmit={submit}>
            <h2 id={headingId}>Reopen goal</h2>
            {error && <Callout tone="danger" title="Could not reopen the goal" description={error} />}
            <label className={styles.field}>
                <span>Tell the agent what still needs doing.</span>
                <textarea className={styles.textarea} value={text} onChange={(event) => setText(event.target.value)} disabled={saving} autoFocus />
            </label>
            <div className={styles.actions}>
                <span className={styles.spacer} />
                <Button variant="ghost" onClick={onClose} disabled={saving}>Cancel</Button>
                <Button variant="filled" type="submit" disabled={!text.trim()} loading={saving} loadingLabel="Reopening…">Reopen and run</Button>
            </div>
        </form>
    </Modal>;
}
