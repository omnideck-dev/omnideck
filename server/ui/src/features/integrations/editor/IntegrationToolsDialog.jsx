import { useEffect, useState } from 'react';

import OperationPicker from '../components/OperationPicker.jsx';
import IntegrationEditDialog from './IntegrationEditDialog.jsx';

export default function IntegrationToolsDialog({ record, groups, saving, error, onSave, onClose }) {
    const [draft, setDraft] = useState(record.operation_grants || []);
    useEffect(() => {
        // An authoritative refresh can narrow scopes while the dialog is open.
        setDraft(record.operation_grants || []);
    }, [record.operation_grants]);
    const original = new Set(record.operation_grants || []);
    const selected = new Set(draft);
    const changes = [...new Set([...original, ...selected])].filter(id => original.has(id) !== selected.has(id)).length;
    return (
        <IntegrationEditDialog title="Choose tools" record={record} tools saving={saving} error={error}
            canSave={changes > 0 && record.state === 'running'}
            onSave={() => onSave({ operation_grants: draft })} onClose={onClose}
            status={changes ? `${changes} unsaved ${changes === 1 ? 'change' : 'changes'}` : 'No changes'}>
            <OperationPicker operations={record.operations || []} groups={groups} selectedIds={draft}
                onChange={setDraft} disabled={saving || record.state !== 'running'} scrollMode="contained" collapsible embedded />
        </IntegrationEditDialog>
    );
}
