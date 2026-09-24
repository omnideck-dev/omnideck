import { useCallback, useEffect, useState } from 'react';

/**
 * Application-wide provider catalog.
 *
 * Provider-backed controls live in several Desktop views that remain mounted
 * while the user moves between tabs. Keeping the catalog at the app root
 * prevents each view from retaining its own one-time snapshot after a provider
 * is added, edited, or removed.
 */
export default function useProviders() {
    const [providers, setProviders] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch('/api/providers');
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
            }
            const nextProviders = Array.isArray(data.providers) ? data.providers : [];
            setProviders(nextProviders);
            return nextProviders;
        } catch (err) {
            setError(err?.message || 'Failed to load providers');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    return { providers, loading, error, refresh };
}
