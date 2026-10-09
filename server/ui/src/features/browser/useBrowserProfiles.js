import { useCallback, useEffect, useRef, useState } from 'react';

import { listBrowserProfiles } from './browserApi.js';

function sortProfiles(profiles) {
    return [...profiles].sort((left, right) => {
        if (left.id === 'default') return -1;
        if (right.id === 'default') return 1;
        return left.name.localeCompare(right.name, undefined, { sensitivity: 'base' });
    });
}

/**
 * Owns the Browser profile catalog for the lifetime of the app. AppData calls
 * this once and shares the result with every Browser profile consumer.
 */
export default function useBrowserProfiles() {
    const [state, setState] = useState({
        profiles: [],
        loading: false,
        loaded: false,
        error: null,
    });
    const stateRef = useRef(state);
    const requestRef = useRef(null);
    const revisionRef = useRef(0);
    const mountedRef = useRef(true);

    const commit = useCallback((next) => {
        stateRef.current = next;
        if (mountedRef.current) setState(next);
    }, []);

    const replaceProfiles = useCallback((profiles) => {
        revisionRef.current += 1;
        commit({
            profiles: sortProfiles(profiles),
            loading: false,
            loaded: true,
            error: null,
        });
    }, [commit]);

    const upsertProfile = useCallback((profile) => {
        revisionRef.current += 1;
        const current = stateRef.current;
        const exists = current.profiles.some((item) => item.id === profile.id);
        const profiles = exists
            ? current.profiles.map((item) => (item.id === profile.id ? profile : item))
            : [...current.profiles, profile];
        commit({
            profiles: sortProfiles(profiles),
            loading: false,
            loaded: true,
            error: null,
        });
    }, [commit]);

    const removeProfile = useCallback((profileId) => {
        revisionRef.current += 1;
        commit({
            profiles: stateRef.current.profiles.filter((profile) => profile.id !== profileId),
            loading: false,
            loaded: true,
            error: null,
        });
    }, [commit]);

    const refresh = useCallback(({ force = false } = {}) => {
        if (requestRef.current) return requestRef.current;
        if (stateRef.current.loaded && !force) {
            return Promise.resolve(stateRef.current.profiles);
        }

        commit({ ...stateRef.current, loading: true, error: null });
        const requestRevision = revisionRef.current;
        const request = listBrowserProfiles()
            .then((profiles) => {
                if (revisionRef.current === requestRevision) replaceProfiles(profiles);
                return profiles;
            })
            .catch((error) => {
                if (revisionRef.current === requestRevision) {
                    commit({
                        ...stateRef.current,
                        loading: false,
                        loaded: false,
                        error,
                    });
                }
                throw error;
            })
            .finally(() => {
                if (requestRef.current === request) requestRef.current = null;
            });
        requestRef.current = request;
        return request;
    }, [commit, replaceProfiles]);

    useEffect(() => {
        mountedRef.current = true;
        refresh().catch(() => {});
        return () => {
            mountedRef.current = false;
        };
    }, [refresh]);

    return {
        ...state,
        refresh,
        replaceProfiles,
        upsertProfile,
        removeProfile,
    };
}
