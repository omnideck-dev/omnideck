import { useState, useEffect, useCallback, useRef } from 'react';

const _defaultGetId = (item) => item.id;
const _defaultTransform = (data) => data;

/**
 * Shared hook for sidebar list panels that fetch, refresh, collapse,
 * delete items, and optionally highlight newly-added items.
 *
 * @param {string} endpoint - API endpoint to GET items from
 * @param {object} options
 * @param {number} [options.refreshSignal] - Increment to trigger a re-fetch
 * @param {function} [options.getId] - Extract unique id from an item (default: item => item.id)
 * @param {function} [options.transform] - Transform the JSON response into the items array
 * @param {boolean} [options.startCollapsed] - Whether panel starts collapsed (default: false)
 */
export default function useListPanel(endpoint, {
    refreshSignal = 0,
    getId = _defaultGetId,
    transform = _defaultTransform,
    onFetched = null,
    startCollapsed = false,
} = {}) {
    const [items, setItems] = useState([]);
    const [loading, setLoading] = useState(true);
    const [collapsed, setCollapsed] = useState(startCollapsed);
    const [deleting, setDeleting] = useState(null);
    const [newItemIds, setNewItemIds] = useState(new Set());
    // null on first load — we only highlight genuinely new items on subsequent
    // refreshes, not everything visible on initial mount.
    const prevIdsRef = useRef(null);
    const requestIdRef = useRef(0);
    const lastEndpointRef = useRef(endpoint);
    // Pending "clear highlight" timer. Tracked so we can cancel it on unmount
    // (or before scheduling the next one) — otherwise a late fire lands on an
    // unmounted component.
    const highlightTimerRef = useRef(null);

    // Store callbacks in refs so fetchItems doesn't depend on them
    const getIdRef = useRef(getId);
    const transformRef = useRef(transform);
    const onFetchedRef = useRef(onFetched);
    getIdRef.current = getId;
    transformRef.current = transform;
    onFetchedRef.current = onFetched;

    const fetchItems = useCallback(async () => {
        const requestId = requestIdRef.current + 1;
        requestIdRef.current = requestId;
        if (lastEndpointRef.current !== endpoint) {
            // A changed endpoint represents a different list scope (for
            // example, all artifacts versus one conversation). Do not show or
            // highlight rows carried over from the previous scope.
            lastEndpointRef.current = endpoint;
            prevIdsRef.current = null;
            setItems([]);
            setNewItemIds(new Set());
        }
        setLoading(true);
        try {
            const resp = await fetch(endpoint);
            if (resp.ok && requestId === requestIdRef.current) {
                const data = await resp.json();
                const fresh = transformRef.current(data);
                const currentGetId = getIdRef.current;
                const freshIds = new Set(fresh.map(currentGetId));
                if (prevIdsRef.current !== null) {
                    const added = fresh
                        .filter((item) => !prevIdsRef.current.has(currentGetId(item)))
                        .map(currentGetId);
                    if (added.length > 0) {
                        setNewItemIds(new Set(added));
                        clearTimeout(highlightTimerRef.current);
                        highlightTimerRef.current = setTimeout(() => setNewItemIds(new Set()), 700);
                    }
                }
                prevIdsRef.current = freshIds;
                setItems(fresh);
                if (onFetchedRef.current) onFetchedRef.current(data);
            }
        } catch (_) {
            // ignore
        } finally {
            // A slower response for an obsolete filter must not clear the
            // loading state owned by the current request.
            if (requestId === requestIdRef.current) setLoading(false);
        }
    }, [endpoint]);

    useEffect(() => { fetchItems(); }, [fetchItems]);
    useEffect(() => { if (refreshSignal > 0) fetchItems(); }, [refreshSignal, fetchItems]);
    useEffect(() => () => clearTimeout(highlightTimerRef.current), []);

    const handleDelete = useCallback(async (key, deleteEndpoint, matchFn) => {
        setDeleting(key);
        try {
            const resp = await fetch(deleteEndpoint, { method: 'DELETE' });
            if (resp.ok || resp.status === 404) {
                setItems((prev) => prev.filter(matchFn));
                return { ok: true, status: resp.status };
            }
            let message = `Delete failed with status ${resp.status}.`;
            try {
                const body = await resp.json();
                if (body?.error) message = body.error;
            } catch (_) {
                // Keep the status-based fallback for non-JSON error responses.
            }
            return { ok: false, status: resp.status, message };
        } catch (_) {
            return {
                ok: false,
                status: 0,
                message: 'Could not reach the server. The item was not deleted.',
            };
        } finally {
            setDeleting(null);
        }
    }, []);

    return {
        items,
        setItems,
        loading,
        collapsed,
        setCollapsed,
        deleting,
        handleDelete,
        newItemIds,
        refetch: fetchItems,
    };
}
