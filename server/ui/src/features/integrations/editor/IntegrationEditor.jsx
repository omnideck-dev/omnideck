import { useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import Modal from '../../../components/primitives/Modal.jsx';
import { getConnectionAdapter } from '../catalog/adapterRegistry.js';
import IntegrationIcon from '../components/IntegrationIcon.jsx';
import { operationGroups } from '../components/OperationPicker.jsx';
import { operationTitle } from '../components/operationDisplay.js';
import IntegrationToolsDialog from './IntegrationToolsDialog.jsx';
import IntegrationRenameDialog from './IntegrationRenameDialog.jsx';
import styles from './IntegrationEditor.module.css';

export default function IntegrationEditor({
    record, catalogEntry, saving, saveError, removeError,
    onSave, onRemove, onReconnect, onClearSaveError,
}) {
    const [dialog, setDialog] = useState(null);
    const [removing, setRemoving] = useState(false);
    const adapter = getConnectionAdapter(record.slug);
    const groups = operationGroups(record.operations || [], catalogEntry?.operation_groups || []);
    const selected = new Set(record.operation_grants || []);
    const selectedCount = groups.reduce((count, group) => count + group.operations.filter(
        operation => selected.has(operation.id) && !operation.unavailable_reason,
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
            </header>
            {record.state !== 'running' && (
                <div className={styles.attention}>
                    <Callout tone="warning" title="This integration needs attention"
                        description={`${adapter.updateAction} to restore access.`}>
                        <div className={styles.recoveryAction}>
                            <Button variant="filled" onClick={onReconnect} disabled={saving}
                                data-testid={`integrations-repair-${record.id}`}>
                                {adapter.updateAction}
                            </Button>
                        </div>
                    </Callout>
                </div>
            )}
            <section aria-labelledby="integration-tools-heading">
                <h2 id="integration-tools-heading">What omnideck can do</h2>
                <p className={styles.description}>{toolCount(selectedCount)} for this integration.</p>
                <div className={styles.toolSummary}>
                    {groups.map(group => {
                        const enabled = group.operations.filter(operation => selected.has(operation.id) && !operation.unavailable_reason);
                        return (
                            <section className={styles.summaryGroup} key={group.id} aria-label={group.title}>
                                {groups.length > 1 && <h3>{group.title}</h3>}
                                <p>{enabled.length
                                    ? enabled.map(operationTitle).join(' · ')
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
                <Button variant="danger" className={styles.remove} onClick={() => open('remove')} disabled={saving}
                    data-testid={`integrations-remove-${record.id}`}>Remove integration…</Button>
            </details>
            {dialog === 'remove' && (
                <Modal labelledBy="integration-delete-title" layout="contained"
                    onClose={removing ? undefined : () => setDialog(null)}>
                    <header className={styles.dialogHeader}>
                        <h2 id="integration-delete-title">Delete {record.label}?</h2>
                    </header>
                    <div className={styles.dialogBody}>
                        <p className={styles.description}>This removes the connection and its tool assignments from all agents and skills. Reconnecting later won’t restore those assignments.</p>
                        {removeError && <Callout tone="danger" description={removeError} />}
                    </div>
                    <footer className={styles.dialogFooter}>
                        <div className={styles.actions}>
                            <Button variant="ghost" disabled={removing} onClick={() => setDialog(null)}>Cancel</Button>
                            <Button variant="danger" loading={removing} loadingLabel="Deleting…" onClick={async () => {
                                setRemoving(true);
                                try { await onRemove(); } finally { setRemoving(false); }
                            }}>Delete integration</Button>
                        </div>
                    </footer>
                </Modal>
            )}
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
