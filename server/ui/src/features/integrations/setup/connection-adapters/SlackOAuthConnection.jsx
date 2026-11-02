import { useState } from 'react';

import Button from '../../../../components/primitives/Button.jsx';
import Callout from '../../../../components/primitives/Callout.jsx';
import { ConnectionField, ConnectionFrame } from '../components/ConnectionLayout.jsx';
import OAuthWaiting from '../components/OAuthWaiting.jsx';
import useOAuthSetup from '../hooks/useOAuthSetup.js';
import useMCPConnectionSettings from '../hooks/useMCPConnectionSettings.js';
import SlackSetupInstructions from './SlackSetupInstructions.jsx';
import styles from '../IntegrationSetupFlow.module.css';

export default function SlackOAuthConnection({
    entry, existingConnection = null, onBack, onExit = onBack,
    onBusyChange, onConnectedId, onPendingOAuthChange,
}) {
    const { settings, error: settingsError } = useMCPConnectionSettings(existingConnection?.id);
    const [label, setLabel] = useState(existingConnection?.label || entry.title);
    // Null means untouched: late settings must never overwrite a user's edit.
    const [editedClientId, setClientId] = useState(null);
    const clientId = editedClientId ?? settings?.connection?.client_id ?? '';
    const oauth = useOAuthSetup({ onBusyChange, onConnectedId, onPendingOAuthChange });
    if (['pending', 'committing', 'success'].includes(oauth.status)) {
        return <OAuthWaiting vendor="Slack" committing={oauth.status !== 'pending'}
            authorizeUrl={oauth.pending?.authorize_url} onReopen={oauth.reopen} onExit={onExit} error={oauth.error} />;
    }
    const starting = oauth.status === 'starting';
    const valid = settings?.redirect_uri && label.trim() && /^\d+\.\d+$/.test(clientId.trim());
    const authorize = () => oauth.start({ slug: 'slack', label: label.trim(), client_id: clientId.trim(),
        ...(existingConnection ? { reconnect_id: existingConnection.id } : {}),
    });
    return <ConnectionFrame title="Connect Slack"
        description="Use an internal Slack app owned by your organization. Each person signs in with their own account."
        footer={<>
            <Button variant="ghost" onClick={onBack} disabled={starting}>Back</Button>
            <Button variant="filled" onClick={authorize} disabled={!valid || starting} loading={starting}>Connect</Button>
        </>}>
        {settings?.slack_manifest && <SlackSetupInstructions manifest={settings.slack_manifest} />}
        <ConnectionField label="Connection name">
            <input className={styles.input} value={label} onChange={event => setLabel(event.target.value)} disabled={!!existingConnection || starting} />
        </ConnectionField>
        <ConnectionField label="Slack Client ID" hint="From your Slack app’s Basic Information page. This is a public identifier, not a password.">
            <input className={styles.input} value={clientId} onChange={event => setClientId(event.target.value)}
                placeholder="123456789.123456789" disabled={!settings || starting} spellCheck={false} />
        </ConnectionField>
        <ConnectionField wide label="Redirect URL" hint="Already included in the manifest. Sign in using a browser on the computer running omnideck.">
            <input className={styles.input} value={settings?.redirect_uri || ''} readOnly onFocus={event => event.target.select()} />
        </ConnectionField>
        <Callout tone="info" title="Access in Slack"
            description={'Slack will ask for access to conversations, including private channels and direct messages you can access, '
                + 'and permission to send messages and work with files, canvases, and lists. '
                + (existingConnection
                    ? 'Your selected tools stay the same. After reconnecting, use Change tools to enable any newly available tools.'
                    : 'After signing in, choose which tools omnideck can use.')} />
        {settingsError && <Callout tone="danger" title="Connection settings unavailable" description={settingsError} />}
        {oauth.error && <Callout tone="danger" title="Couldn’t connect" description={oauth.error.message} />}
        {['expired', 'cancelled'].includes(oauth.status) && <Callout tone="info" title="Sign-in ended" description="Connect again when you’re ready." />}
    </ConnectionFrame>;
}
