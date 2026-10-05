import { useState } from 'react';

import Button from '../../../../components/primitives/Button.jsx';
import Callout from '../../../../components/primitives/Callout.jsx';
import { ConnectionField, ConnectionFrame } from '../components/ConnectionLayout.jsx';
import OAuthWaiting from '../components/OAuthWaiting.jsx';
import useOAuthSetup from '../hooks/useOAuthSetup.js';
import useMCPConnectionSettings from '../hooks/useMCPConnectionSettings.js';
import styles from '../IntegrationSetupFlow.module.css';

export default function MCPOAuthConnection({
    entry, existingConnection = null, onBack, onExit = onBack,
    onBusyChange, onConnectedId, onPendingOAuthChange,
}) {
    const { settings, error: settingsError } = useMCPConnectionSettings(existingConnection?.id);
    const redirectUri = settings?.redirect_uri || '';
    const [form, setForm] = useState({
        label: existingConnection?.label || entry.title,
        endpoint: null, issuer: null, clientId: null, scopes: '',
    });
    const oauth = useOAuthSetup({ onBusyChange, onConnectedId, onPendingOAuthChange });
    const set = (key, value) => setForm(current => ({ ...current, [key]: value }));
    const endpoint = form.endpoint ?? settings?.connection?.endpoint ?? '';
    const issuer = form.issuer ?? settings?.connection?.issuer ?? '';
    const clientId = form.clientId ?? settings?.connection?.client_id ?? '';
    if (['pending', 'committing', 'success'].includes(oauth.status)) {
        return <OAuthWaiting vendor={entry.title} committing={oauth.status !== 'pending'}
            authorizeUrl={oauth.pending?.authorize_url} onReopen={oauth.reopen} onExit={onExit} error={oauth.error} />;
    }
    const starting = oauth.status === 'starting';
    const valid = redirectUri && form.label.trim() && endpoint.trim() && (!clientId.trim() || issuer.trim());
    const authorize = () => oauth.start({
        slug: entry.id, label: form.label.trim(),
        endpoint: endpoint.trim(), client_id: clientId.trim(), issuer: issuer.trim(), scopes: form.scopes.trim(),
        ...(existingConnection ? { reconnect_id: existingConnection.id } : {}),
    });
    return (
        <ConnectionFrame title={`Connect ${entry.title}`}
            description="Enter the server address supplied by the service you want to connect."
            footer={<>
                <Button variant="ghost" onClick={onBack} disabled={starting}>Back</Button>
                <Button variant="filled" onClick={authorize} disabled={!valid || starting} loading={starting}>Connect</Button>
            </>}
        >
            <ConnectionField label="Connection name">
                <input className={styles.input} value={form.label} onChange={event => set('label', event.target.value)} disabled={!!existingConnection || starting} />
            </ConnectionField>
            <ConnectionField label="Server URL">
                <input className={styles.input} type="url" value={endpoint} onChange={event => set('endpoint', event.target.value)} placeholder="https://service.example/mcp" disabled={starting} />
            </ConnectionField>
            <details>
                <summary>Sign-in settings</summary>
                <ConnectionField label="Redirect URL" hint="Use this address if the service asks you to register a redirect URL.">
                    <input className={styles.input} value={redirectUri} readOnly onFocus={event => event.target.select()} />
                </ConnectionField>
                <ConnectionField label="Client ID" hint="Leave blank if the service registers clients automatically.">
                    <input className={styles.input} value={clientId} onChange={event => set('clientId', event.target.value)} disabled={starting} />
                </ConnectionField>
                <ConnectionField label="Authorization server" hint="Required with a client ID. Use the issuer URL supplied by the service.">
                    <input className={styles.input} type="url" value={issuer} onChange={event => set('issuer', event.target.value)} disabled={starting} />
                </ConnectionField>
                <ConnectionField label="Requested access" hint="Optional space-separated scopes supplied by the service.">
                    <input className={styles.input} value={form.scopes} onChange={event => set('scopes', event.target.value)} disabled={starting} />
                </ConnectionField>
            </details>
            {oauth.error && <Callout tone="danger" title="Couldn’t connect" description={oauth.error.message} />}
            {settingsError && <Callout tone="danger" title="Connection settings unavailable" description="Close setup and try again." />}
            {['expired', 'cancelled'].includes(oauth.status) && <Callout tone="info" title="Sign-in ended" description="Connect again when you’re ready." />}
        </ConnectionFrame>
    );
}
