import { useEffect, useState } from 'react';

import IntegrationEditDialog from './IntegrationEditDialog.jsx';
import styles from './IntegrationEditor.module.css';

export default function IntegrationRenameDialog({ record, saving, error, onSave, onClose }) {
    const [draft, setDraft] = useState(record.label);
    useEffect(() => setDraft(record.label), [record.label]);
    const label = draft.trim();
    return (
        <IntegrationEditDialog title="Rename integration" record={record} saving={saving} error={error}
            canSave={label.length > 0 && label !== record.label} saveLabel="Save name"
            onSave={() => onSave({ label })} onClose={onClose}>
            <label className={styles.nameLabel} htmlFor={`integration-name-${record.id}`}>Name</label>
            <input id={`integration-name-${record.id}`} className={styles.nameInput} type="text"
                value={draft} disabled={saving} onChange={event => setDraft(event.target.value)}
                data-testid={`integrations-label-input-${record.id}`} />
        </IntegrationEditDialog>
    );
}
