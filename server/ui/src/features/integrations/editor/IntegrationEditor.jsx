import { useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import ConfirmButton from '../../../components/primitives/ConfirmButton.jsx';
import { getConnectionAdapter } from '../catalog/adapterRegistry.js';
import IntegrationIcon from '../components/IntegrationIcon.jsx';
import IntegrationStatus from '../components/IntegrationStatus.jsx';
import { operationGroups } from '../components/OperationPicker.jsx';
import IntegrationToolsDialog from './IntegrationToolsDialog.jsx';
import IntegrationRenameDialog from './IntegrationRenameDialog.jsx';
import styles from './IntegrationEditor.module.css';

export default function IntegrationEditor({
    record, catalogEntry, saving, saveError, removeError,
    onSave, onRemove, onReconnect, onClearSaveError,
}) {
    const [dialog, setDialog] = useState(null);
    const adapter = getConnectionAdapter(record.slug);
    const groups = operationGroups(record.operations || [], catalogEntry?.operation_groups || []);
    const selected = new Set(record.operation_grants || []);
    const selectedCount = groups.reduce((count, group) => count + group.operations.filter(
        operation => selected.has(operation.id),
    ).length, 0);
    const open = (next) => {
        onClearSaveError?.();
        setDialog(next);
    };

    return (
        <div className={styles.editor} data-testid="integration-overview">
            <header className={styles.header}>
                <IntegrationIcon catalogId={record.slug} className={styles.icon} />
                <div className={styles.identity}>
                    <h1>{record.label}</h1>
                    <p>{catalogEntry?.title || 'Integration'}</p>
                </div>
                <IntegrationStatus state={record.state} />
            </header>
            {record.state !== 'running' && (
                <Callout tone="warning" title="This integration needs attention"
                    description={`Use “${adapter.updateAction}” in Connection settings to restore access.`} />
            )}
            <section aria-labelledby="integration-tools-heading">
                <h2 id="integration-tools-heading">What omnideck can do</h2>
                <p className={styles.description}>{toolCount(selectedCount)} for this integration.</p>
                <div className={styles.toolSummary}>
                    {groups.map(group => {
                        const enabled = group.operations.filter(operation => selected.has(operation.id));
                        return (
                            <section className={styles.summaryGroup} key={group.id} aria-label={group.title}>
                                <div className={styles.summaryHeading}>
                                    <h3>{group.title}</h3><span>{toolCount(enabled.length)}</span>
                                </div>
                                <p>{enabled.length
                                    ? enabled.map(operation => operation.title || 'Unnamed tool').join(' · ')
                                    : 'No tools selected'}</p>
                            </section>
                        );
                    })}
                    {groups.length === 0 && <p className={styles.description}>No tools are currently available.</p>}
                </div>
                <Button variant="filled" onClick={() => open('tools')}
                    disabled={saving || record.state !== 'running'} data-testid={`integrations-change-tools-${record.id}`}>
                    Change tools
                </Button>
            </section>
            <details className={styles.connection}>
                <summary>Connection settings</summary>
                <div className={styles.settingsRow}>
                    <div className={styles.settingCopy}><h3>Name</h3><p>{record.label}</p></div>
                    <Button onClick={() => open('rename')} disabled={saving} data-testid={`integrations-rename-${record.id}`}>Rename</Button>
                </div>
                <div className={styles.settingsRow}>
                    <div className={styles.settingCopy}>
                        <h3>{adapter.updateTitle}</h3>
                        {/* Identity is not part of public metadata. Never infer an email
                            from the editable label or expose vault data here. */}
                        <p>{adapter.updateDescription}</p>
                    </div>
                    <Button onClick={onReconnect} disabled={saving} data-testid={`integrations-reconnect-${record.id}`}>
                        {adapter.updateAction}
                    </Button>
                </div>
                <ConfirmButton className={styles.remove} label="Remove integration" confirmLabel="Confirm removal?"
                    busyLabel="Removing…" title="Remove this integration" onConfirm={onRemove} disabled={saving}
                    data-testid={`integrations-remove-${record.id}`} />
                {removeError && <Callout tone="danger" description={removeError} />}
            </details>
            {dialog === 'tools' && (
                <IntegrationToolsDialog record={record} groups={catalogEntry?.operation_groups || []}
                    saving={saving} error={saveError} onSave={onSave} onClose={() => setDialog(null)} />
            )}
            {dialog === 'rename' && (
                <IntegrationRenameDialog record={record} saving={saving} error={saveError}
                    onSave={onSave} onClose={() => setDialog(null)} />
            )}
        </div>
    );
}

function toolCount(count) {
    return `${count} ${count === 1 ? 'tool' : 'tools'} selected`;
}
