import { useCallback, useEffect, useState } from 'react';

import { integrationError, listIntegrationCatalog, listIntegrations } from '../api/integrationsApi.js';

export default function useIntegrations() {
    const [integrations, setIntegrations] = useState([]);
    const [catalog, setCatalog] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const load = useCallback(async (showLoading) => {
        if (showLoading) setLoading(true);
        setError(null);
        try {
            const [connections, catalogEntries] = await Promise.all([
                listIntegrations(),
                listIntegrationCatalog(),
            ]);
            setIntegrations(connections);
            setCatalog(catalogEntries);
            return connections;
        } catch (requestError) {
            setIntegrations([]);
            setError(integrationError(requestError, 'Failed to load integrations'));
            return [];
        } finally {
            if (showLoading) setLoading(false);
        }
    }, []);

    const refresh = useCallback(() => load(false), [load]);

    useEffect(() => { load(true); }, [load]);

    return { integrations, catalog, loading, error, refresh };
}
