import { useState } from 'react';

import Callout from '../../../../components/primitives/Callout.jsx';
import { errorCopy, getConnectionAdapter } from '../../catalog/adapterRegistry.js';
import {
    ConnectionActions,
    ConnectionField,
    ConnectionFrame,
} from '../components/ConnectionLayout.jsx';
import useConnectionSubmission from '../hooks/useConnectionSubmission.js';
import styles from '../IntegrationSetupFlow.module.css';

export default function HttpTokenConnection({
    entry, existingConnection = null, onBack, onConnected, onBusyChange,
}) {
    const adapter = getConnectionAdapter(entry.id);
    const [form, setForm] = useState({
        label: existingConnection?.label || '',
        baseUrl: '',
        headerName: 'Authorization',
        headerTemplate: 'Bearer {token}',
        token: '',
    });
    const { error, submit, submitting } = useConnectionSubmission({
        entry,
        existingConnection,
        onConnected,
        onBusyChange,
        errorFallback: 'Failed to connect API',
    });
    const canSubmit = form.label.trim() && form.baseUrl.trim() && form.token.trim() && !submitting;
    const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

    const connect = async () => {
        if (!canSubmit) return;
        await submit({
            authBlob: {
                base_url: form.baseUrl.trim(),
                header_name: form.headerName.trim(),
                header_template: form.headerTemplate.trim(),
                token: form.token,
            },
            label: form.label.trim(),
        });
    };

    const copy = error ? errorCopy(error, entry) : null;
    return (
        <ConnectionFrame
            title={existingConnection ? adapter.updateAction : 'Connect an HTTP API'}
            description="Configure one authenticated API base URL."
            footer={(
                <ConnectionActions
                    onBack={onBack}
                    onSubmit={connect}
                    submitting={submitting}
                    submitDisabled={!canSubmit}
                    submitLabel={existingConnection ? adapter.updateAction : 'Connect'}
                    busyLabel={existingConnection ? 'Updating…' : 'Connecting…'}
                />
            )}
        >
            <ConnectionField label="Connection name" hint="A name you will recognize in the integration list.">
                <input
                    className={styles.input}
                    value={form.label}
                    onChange={event => set('label', event.target.value)}
                    placeholder="Sales API"
                    data-testid="wizard-label"
                    disabled={!!existingConnection}
                />
            </ConnectionField>
            <ConnectionField label="Base URL" hint="Requests are resolved relative to this URL.">
                <input
                    className={`${styles.input} ${styles.mono}`}
                    type="url"
                    value={form.baseUrl}
                    onChange={event => set('baseUrl', event.target.value)}
                    placeholder="https://api.example.com/v1"
                    data-testid="wizard-base-url"
                />
            </ConnectionField>
            <div className={styles.fieldPair}>
                <ConnectionField label="Header name">
                    <input
                        className={`${styles.input} ${styles.mono}`}
                        value={form.headerName}
                        onChange={event => set('headerName', event.target.value)}
                        data-testid="wizard-header-name"
                    />
                </ConnectionField>
                <ConnectionField label="Header template" hint="Use {token} where the secret belongs.">
                    <input
                        className={`${styles.input} ${styles.mono}`}
                        value={form.headerTemplate}
                        onChange={event => set('headerTemplate', event.target.value)}
                        data-testid="wizard-header-template"
                    />
                </ConnectionField>
            </div>
            <ConnectionField label="Token" wide>
                <input
                    className={`${styles.input} ${styles.mono}`}
                    type="password"
                    value={form.token}
                    onChange={event => set('token', event.target.value)}
                    placeholder="Paste token"
                    data-testid="wizard-token"
                />
            </ConnectionField>
            {copy && <Callout tone="danger" title={copy.title} description={copy.description} />}
        </ConnectionFrame>
    );
}
