import { useCallback, useEffect, useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
import BrandTabs from '../../../components/primitives/BrandTabs.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import ConfirmButton from '../../../components/primitives/ConfirmButton.jsx';
import IntegrationIcon from '../components/IntegrationIcon.jsx';
import IntegrationStatusBadge, { STATUS_VIEW } from '../components/IntegrationStatusBadge.jsx';
import OperationPicker from '../components/OperationPicker.jsx';
import styles from '../IntegrationsView.module.css';

const TABS = [
    { id: 'tools', label: 'Tools' },
    { id: 'connection', label: 'Connection' },
];

function sameIds(left, right) {
    if (left.length !== right.length) return false;
    const rightSet = new Set(right);
    return left.every(item => rightSet.has(item));
}

export default function IntegrationEditor({
    record,
    catalogEntry,
    saving,
    saveError,
    removeError,
    onSave,
    onRemove,
    onReconnect,
}) {
    const [activeTab, setActiveTab] = useState('tools');
    const [labelDraft, setLabelDraft] = useState(record.label);
    const [grantsDraft, setGrantsDraft] = useState(record.operation_grants || []);
    const label = labelDraft.trim();
    const grantsDirty = !sameIds(grantsDraft, record.operation_grants || []);
    const dirty = label !== record.label || grantsDirty;
    const canSave = dirty && label.length > 0 && !saving;
    const status = STATUS_VIEW[record.state] || STATUS_VIEW.broken;

    useEffect(() => {
        // Saves and reconnects refresh the same record id in place. Mirror the
        // authoritative response so scope narrowing and server normalization
        // cannot leave stale operation selections in the editor.
        setLabelDraft(record.label);
        setGrantsDraft(record.operation_grants || []);
    }, [record.label, record.operation_grants]);

    const save = useCallback(async () => {
        if (!canSave) return;
        const updates = {};
        if (label !== record.label) updates.label = label;
        if (grantsDirty) updates.operation_grants = grantsDraft;
        await onSave(updates);
    }, [canSave, grantsDirty, grantsDraft, label, onSave, record.label]);

    const revert = useCallback(() => {
        setLabelDraft(record.label);
        setGrantsDraft(record.operation_grants || []);
    }, [record]);

    return (
        <div className={styles.editor}>
            <div className={styles.editorHeader}>
                <div className={styles.editorIdentity}>
                    <IntegrationIcon catalogId={record.slug} className={styles.editorIcon} />
                    <div>
                        <h1>{record.label}</h1>
                        <div className={styles.editorMeta}>
                            <span>{catalogEntry?.title || record.slug}</span>
                            <IntegrationStatusBadge state={record.state} />
                        </div>
                    </div>
                </div>
                <div className={styles.editorActions}>
                    <ConfirmButton
                        label="Delete"
                        confirmLabel="Confirm?"
                        busyLabel="Deleting…"
                        title="Delete this integration"
                        onConfirm={onRemove}
                        data-testid={`integrations-remove-${record.id}`}
                    />
                    <Button
                        onClick={revert}
                        disabled={!dirty || saving}
                        data-testid={`integrations-cancel-${record.id}`}
                    >
                        Revert
                    </Button>
                    <Button
                        variant="filled"
                        onClick={save}
                        disabled={!canSave}
                        data-testid={`integrations-save-${record.id}`}
                    >
                        {saving ? 'Saving…' : 'Save'}
                    </Button>
                </div>
            </div>

            <BrandTabs
                tabs={TABS.map(tab => (
                    tab.id === 'tools' ? { ...tab, count: grantsDraft.length } : tab
                ))}
                activeTab={activeTab}
                onTabChange={setActiveTab}
                ariaLabel="Integration settings"
                testIdPrefix="integration-editor-tab"
                idBase="integration-editor"
            />

            <div
                className={`${styles.editorBody} ${activeTab === 'tools' ? styles.editorToolsBody : ''}`}
                id={`integration-editor-panel-${activeTab}`}
                role="tabpanel"
                aria-labelledby={`integration-editor-tab-${activeTab}`}
            >
                {record.state !== 'running' && (
                    <Callout
                        tone="warning"
                        title={status.label === 'auth failed' ? 'Connection needs new credentials' : 'Connection is not running'}
                        description="Open Connection and reconnect this integration before using its tools."
                    />
                )}
                {activeTab === 'tools' && (
                    <section className={`${styles.editorSection} ${styles.editorTools}`} aria-label="Agent tools">
                        <div className={styles.sectionIntro}>
                            <div>
                                <h2>Agent tools</h2>
                                <p>Choose the operations available to the agent through this connection.</p>
                            </div>
                            <div className={styles.sectionCount}>
                                <strong>{grantsDraft.length}</strong>
                                <span>of {record.operations?.length || 0} enabled</span>
                            </div>
                        </div>
                        <OperationPicker
                            operations={record.operations || []}
                            groups={catalogEntry?.operation_groups || []}
                            selectedIds={grantsDraft}
                            onChange={setGrantsDraft}
                            disabled={record.state !== 'running'}
                            scrollMode="contained"
                        />
                    </section>
                )}
                {activeTab === 'connection' && (
                    <ConnectionDetails
                        record={record}
                        catalogEntry={catalogEntry}
                        labelDraft={labelDraft}
                        onLabelChange={setLabelDraft}
                        onReconnect={onReconnect}
                    />
                )}
                {saveError && <Callout tone="danger" description={saveError} />}
                {removeError && <Callout tone="danger" description={removeError} />}
            </div>
        </div>
    );
}

function ConnectionDetails({ record, catalogEntry, labelDraft, onLabelChange, onReconnect }) {
    return (
        <section className={styles.editorSection}>
            <div className={styles.sectionIntro}>
                <div>
                    <h2>Connection</h2>
                    <p>Credentials are encrypted locally and cannot be viewed or edited inline.</p>
                </div>
                <Button onClick={onReconnect} data-testid={`integrations-reconnect-${record.id}`}>
                    <i className="bi bi-arrow-repeat" /> Reconnect
                </Button>
            </div>
            <div className={styles.connectionDetails}>
                <label className={styles.sectionLabel} htmlFor={`integration-name-${record.id}`}>
                    Connection name
                </label>
                <input
                    id={`integration-name-${record.id}`}
                    className={styles.nameInput}
                    type="text"
                    value={labelDraft}
                    onChange={event => onLabelChange(event.target.value)}
                    data-testid={`integrations-label-input-${record.id}`}
                />
                <p className={styles.helpText}>This label is only used inside omnideck.</p>
                <KvRow label="Integration" value={catalogEntry?.title || record.slug} />
                <KvRow label="Status" value={record.state === 'running' ? 'Connected' : record.state} />
                <KvRow label="Credential storage" value="Encrypted locally" />
            </div>
        </section>
    );
}

function KvRow({ label, value }) {
    return <div className={styles.kv}><span>{label}</span><strong>{value}</strong></div>;
}
