import { useCallback, useEffect, useRef, useState } from 'react';

const EMPTY_STATE = { apps: [], loading: false, loaded: false, error: '' };

/** Shared discovery data for the Custom Apps library and app deep links. */
export default function useCustomAppsCatalog({ enabled }) {
    const [state, setState] = useState(EMPTY_STATE);
    const requestIdRef = useRef(0);

    const refresh = useCallback(async () => {
        if (!enabled) return;
        const requestId = ++requestIdRef.current;
        setState((current) => ({ ...current, loading: true, error: '' }));
        try {
            const response = await fetch('/api/custom-apps');
            const body = await response.json();
            if (!response.ok) throw new Error('Could not load Custom Apps');
            if (requestId !== requestIdRef.current) return;
            setState({ apps: body.apps || [], loading: false, loaded: true, error: '' });
        } catch (error) {
            if (requestId !== requestIdRef.current) return;
            setState((current) => ({
                ...current,
                loading: false,
                loaded: true,
                error: error.message || 'Could not load Custom Apps',
            }));
        }
    }, [enabled]);

    useEffect(() => {
        if (enabled) return;
        requestIdRef.current += 1;
        setState(EMPTY_STATE);
    }, [enabled]);

    const findBySlug = useCallback(
        (slug) => state.apps.find((app) => app.slug === slug) || null,
        [state.apps],
    );

    return { ...state, refresh, findBySlug };
}
