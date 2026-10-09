import { useEffect, useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import IconButton from '../../../components/primitives/IconButton.jsx';
import Modal from '../../../components/primitives/Modal.jsx';
import styles from './IntegrationEditor.module.css';

/** Shared edit chrome; drafts and payloads belong to the focused editor. */
export default function IntegrationEditDialog({
    title, record, saving, error, canSave, onSave, onClose, children,
    saveLabel = 'Save changes', status, tools = false,
}) {
    const [takingLonger, setTakingLonger] = useState(false);
    useEffect(() => {
        if (!saving) { setTakingLonger(false); return; }
        const timer = window.setTimeout(() => setTakingLonger(true), 3000);
        return () => window.clearTimeout(timer);
    }, [saving]);
    return (
        <Modal onClose={saving ? undefined : onClose} width={tools ? 760 : 440}
            labelledBy="integration-edit-title" layout="contained"
            testId={tools ? 'integration-tools-dialog' : 'integration-rename-dialog'}>
            <form className={styles.dialogForm} onSubmit={async event => {
                event.preventDefault();
                if (canSave && !saving && await onSave()) onClose();
            }}>
                <header className={styles.dialogHeader}>
                    <div><h2 id="integration-edit-title">{title}</h2><p>{record.label}</p></div>
                    <IconButton aria-label="Close" disabled={saving} onClick={onClose}><i className="bi bi-x-lg" /></IconButton>
                </header>
                <div className={`${styles.dialogBody} ${tools ? styles.toolsBody : ''}`}>
                    {children}
                    {takingLonger && <Callout tone="info" description="Still saving—waiting for the integration service." />}
                    {error && <Callout tone="danger" description={error} />}
                </div>
                <footer className={styles.dialogFooter}>
                    <span className={styles.description} aria-live="polite">{status}</span>
                    <div className={styles.actions}>
                        <Button variant="ghost" onClick={onClose} disabled={saving} data-testid={`integrations-cancel-${record.id}`}>Cancel</Button>
                        <Button type="submit" variant="filled" disabled={!canSave || saving}
                            loading={saving} loadingLabel="Saving…" data-testid={`integrations-save-${record.id}`}>
                            {saveLabel}
                        </Button>
                    </div>
                </footer>
            </form>
        </Modal>
    );
}
