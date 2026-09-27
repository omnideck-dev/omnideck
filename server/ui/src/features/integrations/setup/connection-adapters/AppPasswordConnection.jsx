import { useMemo, useState } from 'react';

import Callout from '../../../../components/primitives/Callout.jsx';
import { errorCopy, getConnectionAdapter } from '../../catalog/adapterRegistry.js';
import {
    ConnectionActions,
    ConnectionField,
    ConnectionFrame,
} from '../components/ConnectionLayout.jsx';
import useConnectionSubmission from '../hooks/useConnectionSubmission.js';
import styles from '../IntegrationSetupFlow.module.css';

export default function AppPasswordConnection({
    entry, existingConnection = null, onBack, onConnected, onBusyChange,
}) {
    const adapter = getConnectionAdapter(entry.id);
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [label, setLabel] = useState(existingConnection?.label || '');
    const { error, submit, submitting } = useConnectionSubmission({
        entry,
        existingConnection,
        onConnected,
        onBusyChange,
        errorFallback: 'Failed to connect integration',
    });
    const canSubmit = email.trim() && password.trim() && !submitting;
    const effectiveLabel = useMemo(
        () => label.trim() || `${entry.title} · ${email.trim()}`,
        [entry.title, email, label],
    );

    const connect = async () => {
        if (!canSubmit) return;
        await submit({
            authBlob: { email: email.trim(), password: password.trim() },
            label: effectiveLabel,
        });
    };

    const copy = error ? errorCopy(error, entry) : null;
    return (
        <ConnectionFrame
            title={existingConnection ? adapter.updateAction : `Connect ${entry.title}`}
            description={`Use an app-specific password from ${adapter.vendor}.`}
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
            <a
                className={styles.externalLink}
                href={adapter.appPasswordUrl}
                target="_blank"
                rel="noopener noreferrer"
            >
                <span><i className="bi bi-box-arrow-up-right" /> Create an app password</span>
                <small>{adapter.appPasswordHost}</small>
            </a>
            <ConnectionField label="Account email" hint="The account omnideck will connect.">
                <input
                    className={styles.input}
                    type="email"
                    placeholder={adapter.emailPlaceholder}
                    value={email}
                    onChange={event => setEmail(event.target.value)}
                    data-testid="wizard-email"
                />
            </ConnectionField>
            <ConnectionField label="App-specific password" hint="Paste the generated password, including dashes if shown.">
                <input
                    className={styles.input}
                    type="password"
                    placeholder="xxxx-xxxx-xxxx-xxxx"
                    value={password}
                    onChange={event => setPassword(event.target.value)}
                    data-testid="wizard-password"
                />
            </ConnectionField>
            <ConnectionField
                label="Connection name"
                hint={`Optional. Defaults to “${entry.title} · account”.`}
                wide
            >
                <input
                    className={styles.input}
                    value={label}
                    onChange={event => setLabel(event.target.value)}
                    placeholder={effectiveLabel || `${entry.title} · account`}
                    data-testid="wizard-label"
                    disabled={!!existingConnection}
                />
            </ConnectionField>
            {copy && <Callout tone="danger" title={copy.title} description={copy.description} />}
        </ConnectionFrame>
    );
}
