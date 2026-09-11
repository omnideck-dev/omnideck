import { useState } from 'react';

import Callout from '../../../../components/primitives/Callout.jsx';
import { errorCopy } from '../../catalog/adapterRegistry.js';
import {
    ConnectionActions,
    ConnectionField,
    ConnectionFrame,
} from '../components/ConnectionLayout.jsx';
import useConnectionSubmission from '../hooks/useConnectionSubmission.js';
import styles from '../IntegrationSetupFlow.module.css';

export default function TestConnection({
    entry, existingConnection = null, onBack, onConnected, onBusyChange,
}) {
    const [token, setToken] = useState('');
    const [label, setLabel] = useState(existingConnection?.label || '');
    const { error, submit, submitting } = useConnectionSubmission({
        entry,
        existingConnection,
        onConnected,
        onBusyChange,
        errorFallback: 'Failed to connect test integration',
    });
    const effectiveLabel = label.trim();
    const canSubmit = effectiveLabel && token && !submitting;

    const connect = async () => {
        if (!canSubmit) return;
        await submit({ authBlob: { token }, label: effectiveLabel });
    };

    const copy = error ? errorCopy(error, entry) : null;
    return (
        <ConnectionFrame
            title={`${existingConnection ? 'Reconnect' : 'Connect'} ${entry.title}`}
            description="Use the deterministic local broker to exercise the complete integration lifecycle without contacting an external service."
            footer={(
                <ConnectionActions
                    onBack={onBack}
                    onSubmit={connect}
                    submitting={submitting}
                    submitDisabled={!canSubmit}
                    submitLabel={existingConnection ? 'Reconnect' : 'Connect'}
                />
            )}
        >
            <Callout
                tone="info"
                title="Development-only integration"
                description="Use omnideck-test-token as the test credential. No network request is made."
            />
            <ConnectionField label="Test credential" hint="Enter omnideck-test-token for a successful connection.">
                <input
                    className={`${styles.input} ${styles.mono}`}
                    type="password"
                    value={token}
                    onChange={event => setToken(event.target.value)}
                    placeholder="omnideck-test-token"
                    data-testid="wizard-token"
                />
            </ConnectionField>
            <ConnectionField label="Connection name" hint="Used to identify this local test connection.">
                <input
                    className={styles.input}
                    value={label}
                    onChange={event => setLabel(event.target.value)}
                    placeholder="Local integration test"
                    data-testid="wizard-label"
                    disabled={!!existingConnection}
                />
            </ConnectionField>
            {copy && <Callout tone="danger" title={copy.title} description={copy.description} />}
        </ConnectionFrame>
    );
}
