import { useCallback, useRef, useState } from 'react';

import {
    createIntegration,
    integrationError,
    reconnectIntegration,
} from '../../api/integrationsApi.js';

export default function useConnectionSubmission({
    entry,
    existingConnection,
    onConnected,
    onBusyChange,
    errorFallback,
}) {
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState(null);
    const inFlight = useRef(false);

    const submit = useCallback(async ({ authBlob, label }) => {
        if (inFlight.current) return null;
        inFlight.current = true;
        setSubmitting(true);
        onBusyChange?.(true);
        setError(null);
        try {
            const record = existingConnection
                ? await reconnectIntegration(existingConnection.id, authBlob)
                : await createIntegration({
                    slug: entry.id,
                    label,
                    auth_blob: authBlob,
                    operation_grants: [],
                });
            onConnected(record);
            return record;
        } catch (requestError) {
            setError(integrationError(requestError, errorFallback));
            return null;
        } finally {
            inFlight.current = false;
            setSubmitting(false);
            onBusyChange?.(false);
        }
    }, [
        entry.id,
        errorFallback,
        existingConnection,
        onBusyChange,
        onConnected,
    ]);

    return { error, submit, submitting };
}
