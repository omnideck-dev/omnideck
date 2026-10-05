import { useState } from 'react';

import Button from '../../../../components/primitives/Button.jsx';
import Callout from '../../../../components/primitives/Callout.jsx';
import useOAuthSetup from '../hooks/useOAuthSetup.js';
import { errorCopy, getConnectionAdapter, slugify } from '../../catalog/adapterRegistry.js';
import { ConnectionField, ConnectionFrame } from '../components/ConnectionLayout.jsx';
import styles from '../IntegrationSetupFlow.module.css';
import GoogleCloudSetupInstructions from './GoogleCloudSetupInstructions.jsx';

export default function GoogleOAuthConnection({
    entry,
    existingConnection = null,
    onBack,
    onExit = onBack,
    onConnectedId,
    onBusyChange,
    onPendingOAuthChange,
}) {
    const adapter = getConnectionAdapter(entry.id);
    const [form, setForm] = useState({
        email: '',
        label: existingConnection?.label || '',
        clientId: '',
        clientSecret: '',
    });
    const { pending, status, error, start, reopen } = useOAuthSetup({
        onBusyChange, onConnectedId, onPendingOAuthChange,
    });
    const connecting = ['starting', 'pending', 'committing'].includes(status);
    const canSubmit = (existingConnection || form.email.trim()) && form.clientId.trim()
        && form.clientSecret.trim() && !connecting;
    const set = (key, value) => setForm(current => ({ ...current, [key]: value }));

    const authorize = async () => {
        if (!canSubmit) return;
        await start({
                slug: entry.id,
                label: form.label.trim() || `${entry.title} · ${form.email.trim()}`,
                client_id: form.clientId.trim(),
                client_secret: form.clientSecret.trim(),
                scopes: adapter.scopes,
                operation_grants: [],
                ...(existingConnection
                    ? { reconnect_id: existingConnection.id }
                    : { user_suffix: slugify(form.email.split('@')[0]) }),
        });
    };

    if (pending && (status === 'pending' || status === 'committing')) {
        return (
            <ConnectionFrame
                title="Authorize on Google"
                description="A Google sign-in window has opened. Sign in with the account you want to connect and approve access."
                footer={(
                    <>
                        <Button variant="ghost" onClick={onExit} disabled={status === 'committing'}>
                            Exit setup
                        </Button>
                        <Button
                            variant="filled"
                            onClick={reopen}
                            disabled={status === 'committing'}
                            data-testid="oauth-reopen-popup"
                        >
                            <i className="bi bi-box-arrow-up-right" /> Reopen sign-in
                        </Button>
                    </>
                )}
            >
                <div className={styles.waiting}>
                    <span className={styles.spinner} />
                    <div>
                        <strong>
                            {status === 'committing'
                                ? 'Finishing connection…'
                                : 'Waiting for authorization…'}
                        </strong>
                        <span>
                            {status === 'committing'
                                ? 'The secure connection is being saved.'
                                : 'Return here after completing the Google sign-in.'}
                        </span>
                    </div>
                </div>
                <Callout
                    tone="info"
                    title="Using your own OAuth client"
                    description="Google may show an unverified-app message for a personal client. Confirm that the client name is yours before continuing."
                />
            </ConnectionFrame>
        );
    }

    const terminalMessage = status === 'denied'
        ? { title: 'Authorization was cancelled', description: 'Start authorization again when you are ready.' }
        : status === 'expired'
            ? { title: 'Authorization expired', description: 'The sign-in link timed out. Start again to create a fresh link.' }
            : error ? errorCopy(error, entry) : null;

    return (
        <ConnectionFrame
            title={existingConnection ? adapter.updateAction : `Connect ${entry.title}`}
            description={existingConnection
                ? 'Confirm your Google client details, then sign in to refresh access.'
                : 'Create a desktop OAuth client in Google Cloud, then authorize the account. Provider access and omnideck’s tool grants are configured separately.'}
            footer={(
                <>
                    <Button variant="ghost" onClick={onBack} disabled={status === 'starting'}>
                        <i className="bi bi-arrow-left" /> Back
                    </Button>
                    <Button
                        variant="filled"
                        onClick={authorize}
                        disabled={!canSubmit || status === 'starting'}
                        data-testid="oauth-authorize"
                    >
                        {status === 'starting' ? 'Starting…' : existingConnection ? 'Sign in with Google' : 'Authorize with Google'}
                    </Button>
                </>
            )}
        >
            {!existingConnection && (
                <ConnectionField label="Account email" hint="Used to identify and label this local connection.">
                    <input
                        className={styles.input}
                        type="email"
                        value={form.email}
                        onChange={event => set('email', event.target.value)}
                        placeholder={adapter.emailPlaceholder}
                        data-testid="wizard-email"
                    />
                </ConnectionField>
            )}
            <ConnectionField label="Connection name" hint="Optional. You can rename the connection later.">
                <input
                    className={styles.input}
                    value={form.label}
                    onChange={event => set('label', event.target.value)}
                    placeholder={`${entry.title} · account`}
                    data-testid="wizard-label"
                    disabled={!!existingConnection}
                />
            </ConnectionField>

            <GoogleCloudSetupInstructions />

            <ConnectionField label="Client ID">
                <input
                    className={`${styles.input} ${styles.mono}`}
                    value={form.clientId}
                    onChange={event => set('clientId', event.target.value)}
                    placeholder="123456789-abc.apps.googleusercontent.com"
                    data-testid="oauth-client-id"
                />
            </ConnectionField>
            <ConnectionField label="Client secret">
                <input
                    className={`${styles.input} ${styles.mono}`}
                    type="password"
                    value={form.clientSecret}
                    onChange={event => set('clientSecret', event.target.value)}
                    placeholder="GOCSPX-…"
                    data-testid="oauth-client-secret"
                />
            </ConnectionField>
            {terminalMessage && (
                <Callout
                    tone="danger"
                    title={terminalMessage.title}
                    description={terminalMessage.description}
                />
            )}
        </ConnectionFrame>
    );
}
