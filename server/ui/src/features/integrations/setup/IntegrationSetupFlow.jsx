import { useCallback, useMemo, useState } from 'react';

import Button from '../../../components/primitives/Button.jsx';
import Callout from '../../../components/primitives/Callout.jsx';
import Modal from '../../../components/primitives/Modal.jsx';
import {
    cancelIntegrationOAuth,
    listIntegrations,
    removeIntegration,
    updateIntegration,
} from '../api/integrationsApi.js';
import IntegrationIcon from '../components/IntegrationIcon.jsx';
import OperationPicker from '../components/OperationPicker.jsx';
import ConnectionStep from './ConnectionStep.jsx';
import styles from './IntegrationSetupFlow.module.css';

const STEPS = [
    { id: 'integration', title: 'Integration' },
    { id: 'connection', title: 'Connection' },
    { id: 'tools', title: 'Tools' },
    { id: 'review', title: 'Review' },
];

export default function IntegrationSetupFlow({ catalog, onExit, onComplete }) {
    const [step, setStep] = useState('integration');
    const [selectedEntryId, setSelectedEntryId] = useState(null);
    const [connection, setConnection] = useState(null);
    const [selectedIds, setSelectedIds] = useState([]);
    const [pendingOAuthState, setPendingOAuthState] = useState(null);
    const [connectionBusy, setConnectionBusy] = useState(false);
    const [saving, setSaving] = useState(false);
    const [cancelling, setCancelling] = useState(false);
    const [error, setError] = useState(null);
    const entry = useMemo(
        () => catalog.find(item => item.id === selectedEntryId) || null,
        [catalog, selectedEntryId],
    );
    const stepIndex = STEPS.findIndex(item => item.id === step);
    const dismissalBlocked = connectionBusy || saving || cancelling;

    const connected = useCallback((record) => {
        setConnection(record);
        setSelectedIds(record.operation_grants || []);
        setPendingOAuthState(null);
        setError(null);
        setStep('tools');
    }, []);

    const connectedById = useCallback(async (integrationId) => {
        setConnectionBusy(true);
        try {
            const integrations = await listIntegrations();
            const record = integrations.find(item => item.id === integrationId);
            if (!record) throw new Error('The connected integration was not returned by the service.');
            connected(record);
        } catch (requestError) {
            setError({
                title: "Setup couldn't continue",
                message: requestError?.message || 'Failed to load the new connection.',
            });
        } finally {
            setConnectionBusy(false);
        }
    }, [connected]);

    const finish = async () => {
        if (!connection || saving) return;
        setSaving(true);
        setError(null);
        try {
            const updated = await updateIntegration(connection.id, {
                operation_grants: selectedIds,
            });
            onComplete(updated);
        } catch (requestError) {
            setError({
                title: "Couldn't add integration",
                message: requestError?.message || 'Failed to enable the selected tools.',
            });
        } finally {
            setSaving(false);
        }
    };

    const cancel = useCallback(async () => {
        if (dismissalBlocked) return;
        if (!connection && !pendingOAuthState) {
            onExit();
            return;
        }

        setCancelling(true);
        setError(null);
        try {
            let integrationId = connection?.id || null;
            if (pendingOAuthState) {
                const cancelled = await cancelIntegrationOAuth(pendingOAuthState);
                integrationId ||= cancelled.integration_id || null;
            }
            if (integrationId) await removeIntegration(integrationId);
            onExit();
        } catch (requestError) {
            setError({
                title: "Couldn't cancel setup",
                message: requestError?.message
                    || 'The new connection could not be removed. Try again.',
            });
        } finally {
            setCancelling(false);
        }
    }, [connection, dismissalBlocked, onExit, pendingOAuthState]);

    return (
        <Modal
            onClose={dismissalBlocked ? undefined : cancel}
            width={760}
            labelledBy="add-integration-title"
            className={styles.modal}
            testId="integration-setup-flow"
        >
            <header className={styles.modalHeader}>
                <div id="add-integration-title" className={styles.modalTitle}>Add integration</div>
                <button
                    type="button"
                    className={styles.closeButton}
                    onClick={cancel}
                    disabled={dismissalBlocked}
                    aria-label="Close"
                >
                    <i className="bi bi-x-lg" />
                </button>
            </header>

            <SetupProgress stepIndex={stepIndex} />

            <div className={styles.stepContent}>
                {error && (
                    <div className={styles.flowError}>
                        <Callout tone="danger" title={error.title} description={error.message} />
                    </div>
                )}
                {step === 'integration' && (
                    <ChooseIntegrationStep
                        catalog={catalog}
                        selectedId={selectedEntryId}
                        onSelect={setSelectedEntryId}
                        onCancel={cancel}
                        onContinue={() => setStep('connection')}
                    />
                )}
                {step === 'connection' && entry && (
                    <ConnectionStep
                        entry={entry}
                        onBack={() => setStep('integration')}
                        onExit={cancel}
                        onConnected={connected}
                        onConnectedId={connectedById}
                        onBusyChange={setConnectionBusy}
                        onPendingOAuthChange={setPendingOAuthState}
                    />
                )}
                {step === 'tools' && entry && connection && (
                    <ToolsStep
                        entry={entry}
                        connection={connection}
                        selectedIds={selectedIds}
                        onChange={setSelectedIds}
                        onCancel={cancel}
                        onContinue={() => setStep('review')}
                        cancelling={cancelling}
                    />
                )}
                {step === 'review' && entry && connection && (
                    <ReviewStep
                        entry={entry}
                        connection={connection}
                        selectedIds={selectedIds}
                        saving={saving}
                        cancelling={cancelling}
                        onCancel={cancel}
                        onBack={() => setStep('tools')}
                        onFinish={finish}
                    />
                )}
            </div>
        </Modal>
    );
}

function SetupProgress({ stepIndex }) {
    return (
        <div className={styles.progress} aria-label="Setup progress">
            {STEPS.map((item, index) => {
                const active = index === stepIndex;
                const done = index < stepIndex;
                return (
                    <div
                        className={`${styles.progressStep} ${active ? styles.progressStepActive : ''} ${done ? styles.progressStepDone : ''}`}
                        key={item.id}
                        aria-current={active ? 'step' : undefined}
                    >
                        <span className={styles.progressNumber}>
                            {done ? <i className="bi bi-check-lg" /> : index + 1}
                        </span>
                        <span>{item.title}</span>
                    </div>
                );
            })}
        </div>
    );
}

function ChooseIntegrationStep({ catalog, selectedId, onSelect, onCancel, onContinue }) {
    const categories = useMemo(() => {
        const grouped = new Map();
        for (const catalogEntry of catalog) {
            const category = catalogEntry.category || 'Other';
            if (!grouped.has(category)) grouped.set(category, []);
            grouped.get(category).push(catalogEntry);
        }
        return [...grouped.entries()];
    }, [catalog]);

    return (
        <div className={styles.stepPage}>
            <div className={styles.modalBody}>
                <div className={styles.pageIntro}>
                    <h1>Choose an integration</h1>
                    <p>Connect a service from the catalog. You’ll choose its individual tools after connecting.</p>
                </div>
                <div className={styles.catalogSections}>
                    {categories.map(([category, entries]) => (
                        <section key={category}>
                            <div className={styles.catalogCategory}>{category}</div>
                            <div className={styles.catalogGrid}>
                                {entries.map(catalogEntry => (
                                    <button
                                        type="button"
                                        className={`${styles.catalogCard} ${selectedId === catalogEntry.id ? styles.catalogCardSelected : ''}`}
                                        key={catalogEntry.id}
                                        onClick={() => onSelect(catalogEntry.id)}
                                        onDoubleClick={() => {
                                            onSelect(catalogEntry.id);
                                            onContinue();
                                        }}
                                        data-testid={`provider-${catalogEntry.id}`}
                                    >
                                        <IntegrationIcon catalogId={catalogEntry.id} className={styles.catalogIcon} />
                                        <span className={styles.catalogCopy}>
                                            <span className={styles.catalogTitle}>{catalogEntry.title}</span>
                                            <span className={styles.catalogDescription}>{catalogEntry.description}</span>
                                        </span>
                                        <i className="bi bi-chevron-right" />
                                    </button>
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            </div>
            <div className={styles.stepFooter}>
                <Button onClick={onCancel}>Cancel</Button>
                <Button
                    variant="filled"
                    onClick={onContinue}
                    disabled={!selectedId}
                    data-testid="wizard-next"
                >
                    Continue <i className="bi bi-arrow-right" />
                </Button>
            </div>
        </div>
    );
}

function ToolsStep({
    entry, connection, selectedIds, onChange, onCancel, onContinue, cancelling,
}) {
    return (
        <div className={styles.stepPage}>
            <div className={`${styles.modalBody} ${styles.toolsBody}`}>
                <div className={styles.pageIntro}>
                    <h1>Choose tools</h1>
                    <p>Select the individual {entry.title} tools omnideck can use. You can change this later.</p>
                </div>
                <OperationPicker
                    operations={connection.operations || []}
                    groups={entry.operation_groups || []}
                    selectedIds={selectedIds}
                    onChange={onChange}
                    disabled={cancelling}
                    scrollMode="contained"
                />
            </div>
            <div className={styles.stepFooter}>
                <Button onClick={onCancel} disabled={cancelling} data-testid="wizard-exit">
                    {cancelling ? 'Cancelling…' : 'Cancel'}
                </Button>
                <Button
                    variant="filled"
                    onClick={onContinue}
                    disabled={cancelling}
                    data-testid="wizard-next"
                >
                    Continue <i className="bi bi-arrow-right" />
                </Button>
            </div>
        </div>
    );
}

function ReviewStep({
    entry, connection, selectedIds, saving, cancelling, onCancel, onBack, onFinish,
}) {
    const selected = new Set(selectedIds);
    const selectedOperations = (connection.operations || []).filter(
        operation => selected.has(operation.id),
    );
    return (
        <div className={styles.stepPage}>
            <div className={styles.modalBody}>
                <div className={styles.pageIntro}>
                    <h1>Review integration</h1>
                    <p>Confirm the connection and tools before adding {entry.title} to omnideck.</p>
                </div>
                <div className={styles.reviewGrid}>
                    <section className={styles.reviewCard}>
                        <h2>Integration</h2>
                        <ReviewRow label="Type" value={entry.title} />
                        <ReviewRow label="Name" value={connection.label} />
                    </section>
                    <section className={styles.reviewCard}>
                        <h2>Connection</h2>
                        <ReviewRow label="Status" value="Connected" />
                        <ReviewRow label="Storage" value="Encrypted locally" />
                    </section>
                    <section className={`${styles.reviewCard} ${styles.reviewTools}`}>
                        <div className={styles.reviewTitleRow}>
                            <h2>{selectedOperations.length} {selectedOperations.length === 1 ? 'tool' : 'tools'} selected</h2>
                            <button type="button" onClick={onBack} disabled={saving || cancelling}>Edit</button>
                        </div>
                        {selectedOperations.length > 0 ? (
                            <ul className={styles.reviewOperationList}>
                                {selectedOperations.map(operation => <li key={operation.id}>{operation.title}</li>)}
                            </ul>
                        ) : (
                            <p className={styles.noTools}>No tools selected.</p>
                        )}
                    </section>
                </div>
            </div>
            <div className={styles.stepFooter}>
                <Button onClick={onCancel} disabled={saving || cancelling}>
                    {cancelling ? 'Cancelling…' : 'Cancel'}
                </Button>
                <div className={styles.footerActions}>
                    <Button onClick={onBack} disabled={saving || cancelling}>
                        <i className="bi bi-arrow-left" /> Back
                    </Button>
                    <Button
                        variant="filled"
                        onClick={onFinish}
                        disabled={saving || cancelling}
                        data-testid="wizard-done"
                    >
                        {saving ? 'Adding…' : 'Add integration'}
                    </Button>
                </div>
            </div>
        </div>
    );
}

function ReviewRow({ label, value }) {
    return <div className={styles.reviewRow}><span>{label}</span><strong>{value}</strong></div>;
}
