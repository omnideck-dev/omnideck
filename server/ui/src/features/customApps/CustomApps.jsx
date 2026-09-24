import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import useCustomAppsCatalog from './useCustomAppsCatalog.js';

const CustomAppsContext = createContext(null);
const PINNED_APPS_KEY = 'omnideck_sidebar_pinned_apps';

function readPinnedAppSlugs() {
    if (typeof localStorage === 'undefined') return [];
    try {
        const stored = JSON.parse(localStorage.getItem(PINNED_APPS_KEY) || '[]');
        if (!Array.isArray(stored)) return [];
        return [
            ...new Set(stored.filter((slug) => typeof slug === 'string' && slug)),
        ];
    } catch {
        return [];
    }
}

function persistPinnedAppSlugs(slugs) {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(PINNED_APPS_KEY, JSON.stringify(slugs));
    } catch {
        // Pinning still works for the session when localStorage is unavailable.
    }
}

/** Owns the shared App catalog and persistent sidebar pinning preferences. */
export function CustomAppsProvider({ children }) {
    const { features, featuresLoaded } = useAppData();
    const enabled = Boolean(features.custom_apps);
    const catalog = useCustomAppsCatalog({ enabled });
    const [pinnedAppSlugs, setPinnedAppSlugs] = useState(readPinnedAppSlugs);

    useEffect(() => {
        if (enabled) catalog.refresh();
    }, [catalog.refresh, enabled]);

    const pinApp = useCallback((slug) => {
        setPinnedAppSlugs((current) => {
            if (!slug || current.includes(slug)) return current;
            const next = [...current, slug];
            persistPinnedAppSlugs(next);
            return next;
        });
    }, []);

    const unpinApp = useCallback((slug) => {
        setPinnedAppSlugs((current) => {
            const next = current.filter((candidate) => candidate !== slug);
            if (next.length === current.length) return current;
            persistPinnedAppSlugs(next);
            return next;
        });
    }, []);

    const reorderPinnedApps = useCallback((orderedSlugs) => {
        setPinnedAppSlugs((current) => {
            const remaining = new Set(current);
            const next = [];
            orderedSlugs.forEach((slug) => {
                if (!remaining.delete(slug)) return;
                next.push(slug);
            });
            current.forEach((slug) => {
                if (remaining.delete(slug)) next.push(slug);
            });
            if (
                next.length === current.length
                && next.every((slug, index) => slug === current[index])
            ) {
                return current;
            }
            persistPinnedAppSlugs(next);
            return next;
        });
    }, []);

    const value = useMemo(() => ({
        enabled,
        featureLoaded: featuresLoaded,
        catalog,
        pinnedAppSlugs,
        pinApp,
        unpinApp,
        reorderPinnedApps,
    }), [
        catalog,
        enabled,
        featuresLoaded,
        pinApp,
        pinnedAppSlugs,
        reorderPinnedApps,
        unpinApp,
    ]);

    return <CustomAppsContext.Provider value={value}>{children}</CustomAppsContext.Provider>;
}

export function useCustomApps() {
    const value = useContext(CustomAppsContext);
    if (value === null) {
        throw new Error('useCustomApps must be used within CustomAppsProvider');
    }
    return value;
}
