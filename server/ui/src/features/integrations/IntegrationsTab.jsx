import { useCallback, useEffect, useMemo, useState } from 'react';

import ListItem from '../../components/ListItem.jsx';
import SplitPanel from '../../components/SplitPanel.jsx';
import Button from '../../components/primitives/Button.jsx';
import Callout from '../../components/primitives/Callout.jsx';
import { removeIntegration, updateIntegration } from './api/integrationsApi.js';
import IntegrationIcon from './components/IntegrationIcon.jsx';
import IntegrationEditor from './editor/IntegrationEditor.jsx';
import useIntegrations from './hooks/useIntegrations.js';
import IntegrationReconnectFlow from './setup/IntegrationReconnectFlow.jsx';
import IntegrationSetupFlow from './setup/IntegrationSetupFlow.jsx';
import styles from './IntegrationsView.module.css';

export default function IntegrationsTab() {
    const { connections, catalog, loading, error: loadError, refresh } = useIntegrations();
    const [setupOpen, setSetupOpen] = useState(false);
    const [reconnectRecord, setReconnectRecord] = useState(null);
    const [selectedId, setSelectedId] = useState(null);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [removeError, setRemoveError] = useState(null);

    useEffect(() => {
        if (connections.length === 0) {
            if (selectedId !== null) setSelectedId(null);
            return;
        }
        if (!connections.some(item => item.id === selectedId)) {
            setSelectedId(connections[0].id);
        }
    }, [connections, selectedId]);

    useEffect(() => {
        setSaveError(null);
        setRemoveError(null);
    }, [selectedId]);

    const catalogById = useMemo(
        () => new Map(catalog.map(entry => [entry.id, entry])),
        [catalog],
    );
    const selected = useMemo(
        () => connections.find(item => item.id === selectedId) || null,
        [connections, selectedId],
    );
    const grouped = useMemo(() => {
        const groups = new Map();
        for (const record of connections) {
            const entry = catalogById.get(record.slug);
            const category = entry?.category || 'Other';
            if (!groups.has(category)) groups.set(category, []);
            groups.get(category).push({ record, entry });
        }
        return [...groups.entries()];
    }, [catalogById, connections]);

    const handleSave = useCallback(async (updates) => {
        if (!selected) return false;
        setSaving(true);
        setSaveError(null);
        try {
            await updateIntegration(selected.id, updates);
            await refresh();
            return true;
        } catch (requestError) {
            setSaveError(requestError?.message || 'Failed to save integration');
            return false;
        } finally {
            setSaving(false);
        }
    }, [refresh, selected]);

    const handleRemove = useCallback(async () => {
        if (!selected) return;
        setRemoveError(null);
        try {
            await removeIntegration(selected.id);
            await refresh();
        } catch (requestError) {
            setRemoveError(requestError?.message || 'Failed to delete integration');
        }
    }, [refresh, selected]);

    const setupComplete = useCallback(async (record) => {
        setSetupOpen(false);
        setReconnectRecord(null);
        const next = await refresh();
        if (record?.id && next.some(item => item.id === record.id)) setSelectedId(record.id);
    }, [refresh]);

    return (
        <div className={styles.container} data-testid="integrations-tab">
            {loading ? (
                <div className={styles.loading}>Loading integrations…</div>
            ) : loadError ? (
                loadError.code === 'UNAVAILABLE' ? (
                    <UnavailableState onRetry={refresh} />
                ) : (
                    <div className={styles.loadError}>
                        <Callout tone="danger" title="Couldn't load integrations" description={loadError.message} />
                        <Button onClick={refresh}><i className="bi bi-arrow-clockwise" /> Retry</Button>
                    </div>
                )
            ) : connections.length === 0 ? (
                <EmptyState onAdd={() => setSetupOpen(true)} />
            ) : (
                <SplitPanel>
                    <SplitPanel.List>
                        <IntegrationList
                            groups={grouped}
                            selectedId={selectedId}
                            onSelect={setSelectedId}
                            onAdd={() => setSetupOpen(true)}
                        />
                    </SplitPanel.List>
                    <SplitPanel.Detail>
                        {selected && (
                            <IntegrationEditor
                                key={selected.id}
                                record={selected}
                                catalogEntry={catalogById.get(selected.slug)}
                                saving={saving}
                                saveError={saveError}
                                removeError={removeError}
                                onSave={handleSave}
                                onClearSaveError={() => setSaveError(null)}
                                onRemove={handleRemove}
                                onReconnect={() => setReconnectRecord(selected)}
                            />
                        )}
                    </SplitPanel.Detail>
                </SplitPanel>
            )}

            {setupOpen && (
                <IntegrationSetupFlow
                    catalog={catalog}
                    onExit={() => setSetupOpen(false)}
                    onComplete={setupComplete}
                />
            )}
            {reconnectRecord && (
                <IntegrationReconnectFlow
                    connection={reconnectRecord}
                    catalogEntry={catalogById.get(reconnectRecord.slug)}
                    onExit={() => setReconnectRecord(null)}
                    onComplete={setupComplete}
                />
            )}
        </div>
    );
}

function EmptyState({ onAdd }) {
    return (
        <div className={styles.emptyState}>
            <div className={styles.emptyIcon}><i className="bi bi-plug" /></div>
            <h1>Connect your first integration</h1>
            <p>Connect email, calendar, drive, contacts, and APIs. Credentials stay encrypted locally, and you choose the exact tools the agent may use.</p>
            <Button variant="filled" onClick={onAdd} data-testid="integrations-add-first">
                <i className="bi bi-plus-lg" /> Add integration
            </Button>
        </div>
    );
}

function UnavailableState({ onRetry }) {
    return (
        <div className={styles.emptyState}>
            <div className={`${styles.emptyIcon} ${styles.emptyIconMuted}`}><i className="bi bi-wifi-off" /></div>
            <h1>Integrations unavailable</h1>
            <p>The integrations service is temporarily unavailable. Try again in a moment.</p>
            <Button onClick={onRetry} data-testid="integrations-retry">
                <i className="bi bi-arrow-clockwise" /> Try again
            </Button>
        </div>
    );
}

function IntegrationList({ groups, selectedId, onSelect, onAdd }) {
    const count = groups.reduce((total, [, rows]) => total + rows.length, 0);
    return (
        <>
            <SplitPanel.Header actions={
                <Button variant="ghost" onClick={onAdd} data-testid="integrations-add-another">
                    <i className="bi bi-plus-lg" /> Add
                </Button>
            }>Integrations · {count}</SplitPanel.Header>
            <div className={styles.listBody}>
                {groups.map(([category, rows]) => (
                    <section className={styles.listGroup} key={category}>
                        <div className={styles.listGroupLabel}>{category}</div>
                        {rows.map(({ record }) => (
                            <ListItem
                                key={record.id}
                                active={record.id === selectedId}
                                aria-current={record.id === selectedId ? 'true' : undefined}
                                icon={<IntegrationIcon catalogId={record.slug} />}
                                name={record.label}
                                description={(record.operation_grants || []).length === 0
                                    ? 'No tools selected'
                                    : `${record.operation_grants.length} ${record.operation_grants.length === 1 ? 'tool' : 'tools'} selected`}
                                onClick={() => onSelect(record.id)}
                                data-testid={`integrations-row-${record.id}`}
                            />
                        ))}
                    </section>
                ))}
            </div>
        </>
    );
}
