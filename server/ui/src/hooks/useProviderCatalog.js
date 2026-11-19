import { useCallback, useEffect, useState } from 'react';

/**
 * The kinds of provider the user can add, in display order, with the
 * label, icon, and form fields for each. The server leaves out kinds that
 * are switched off, so refresh after changing a setting that gates one.
 */
export default function useProviderCatalog() {
    const [catalog, setCatalog] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    const refresh = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const response = await fetch('/api/providers/catalog');
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
            }
            const nextCatalog = Array.isArray(data.providers) ? data.providers : [];
            setCatalog(nextCatalog);
            return nextCatalog;
        } catch (err) {
            setError(err?.message || 'Failed to load the provider catalog');
            return null;
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    return { catalog, loading, error, refresh };
}
