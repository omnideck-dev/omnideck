import { useEffect, useRef, useState } from 'react';

import { getIntegrationOAuthStatus, integrationError, startIntegrationOAuth } from '../../api/integrationsApi.js';

/** Own one explicit authorization attempt; the enclosing flow owns cancellation. */
export default function useOAuthSetup({ onBusyChange, onConnectedId, onPendingOAuthChange }) {
    const [pending, setPending] = useState(null);
    const [status, setStatus] = useState(null);
    const [error, setError] = useState(null);
    const starting = useRef(false);
    const openSignIn = (url) => window.open(url, 'omnideck-integration-oauth', 'width=600,height=720');

    useEffect(() => {
        if (!pending || !['pending', 'committing'].includes(status)) return undefined;
        let cancelled = false;
        let timer;
        const poll = async () => {
            try {
                const next = await getIntegrationOAuthStatus(pending.state);
                if (cancelled) return;
                setError(next.error || null);
                setStatus(next.status);
                onBusyChange?.(next.status === 'committing');
                if (next.status === 'success') {
                    await onConnectedId(next.integration_id);
                    return;
                }
                if (!['pending', 'committing'].includes(next.status)) return;
            } catch (requestError) {
                if (cancelled) return;
                // A dropped poll is not a failed authorization: keep the owned
                // attempt so Retry cannot accidentally create a second account.
                setError(integrationError(requestError, 'Checking sign-in again…'));
            }
            if (!cancelled) timer = window.setTimeout(poll, 1000);
        };
        timer = window.setTimeout(poll, 700);
        return () => { cancelled = true; window.clearTimeout(timer); };
    }, [pending, status, onBusyChange, onConnectedId]);

    const start = async (payload) => {
        if (starting.current) return;
        starting.current = true;
        setError(null);
        setStatus('starting');
        onBusyChange?.(true);
        try {
            const next = await startIntegrationOAuth(payload);
            setPending(next);
            onPendingOAuthChange?.(next.state);
            setStatus(next.status || 'pending');
            setError(next.error || null);
            onBusyChange?.(next.status === 'committing');
            if (next.status === 'success') await onConnectedId(next.integration_id);
            else if (next.authorize_url) openSignIn(next.authorize_url);
        } catch (requestError) {
            setStatus('error');
            setError(integrationError(requestError, 'Could not start sign-in.'));
            onBusyChange?.(false);
        } finally {
            starting.current = false;
        }
    };

    return { pending, status, error, start, reopen: () => pending?.authorize_url && openSignIn(pending.authorize_url) };
}
