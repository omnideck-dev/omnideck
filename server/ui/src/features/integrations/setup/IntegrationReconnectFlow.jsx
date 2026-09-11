import { useCallback, useState } from 'react';

import Callout from '../../../components/primitives/Callout.jsx';
import Modal from '../../../components/primitives/Modal.jsx';
import {
    cancelIntegrationOAuth,
    listIntegrations,
} from '../api/integrationsApi.js';
import ConnectionStep from './ConnectionStep.jsx';
import styles from './IntegrationSetupFlow.module.css';

export default function IntegrationReconnectFlow({
    connection, catalogEntry, onExit, onComplete,
}) {
    const [busy, setBusy] = useState(false);
    const [cancelling, setCancelling] = useState(false);
    const [pendingOAuthState, setPendingOAuthState] = useState(null);
    const [error, setError] = useState(null);

    const connectedById = useCallback(async (integrationId) => {
        setBusy(true);
        try {
            const integrations = await listIntegrations();
            const updated = integrations.find(item => item.id === integrationId);
            if (!updated) throw new Error('The reconnected integration was not returned by the service.');
            onComplete(updated);
        } catch (requestError) {
            setError(requestError?.message || 'Failed to load the reconnected integration.');
        } finally {
            setBusy(false);
        }
    }, [onComplete]);

    const cancel = useCallback(async () => {
        if (busy || cancelling) return;
        if (!pendingOAuthState) {
            onExit();
            return;
        }
        setCancelling(true);
        setError(null);
        try {
            await cancelIntegrationOAuth(pendingOAuthState);
            onExit();
        } catch (requestError) {
            setError(requestError?.message || 'Failed to cancel authorization.');
        } finally {
            setCancelling(false);
        }
    }, [busy, cancelling, onExit, pendingOAuthState]);

    const dismissalBlocked = busy || cancelling;
    return (
        <Modal
            onClose={dismissalBlocked ? undefined : cancel}
            width={760}
            labelledBy="reconnect-integration-title"
            className={styles.modal}
            testId="integration-reconnect-flow"
        >
            <header className={styles.modalHeader}>
                <div id="reconnect-integration-title" className={styles.modalTitle}>
                    Reconnect integration
                </div>
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
            <div className={styles.stepContent}>
                {error && (
                    <div className={styles.flowError}>
                        <Callout
                            tone="danger"
                            title="Reconnect couldn't finish"
                            description={error}
                        />
                    </div>
                )}
                <ConnectionStep
                    entry={catalogEntry}
                    existingConnection={connection}
                    onBack={cancel}
                    onExit={cancel}
                    onConnected={onComplete}
                    onConnectedId={connectedById}
                    onBusyChange={setBusy}
                    onPendingOAuthChange={setPendingOAuthState}
                />
            </div>
        </Modal>
    );
}
