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
const DOCKED_APPS_KEY = 'omnideck_sidebar_docked_apps';

function readDockedAppSlugs() {
    if (typeof localStorage === 'undefined') return [];
    try {
        const stored = JSON.parse(localStorage.getItem(DOCKED_APPS_KEY) || '[]');
        if (!Array.isArray(stored)) return [];
        return [...new Set(stored.filter((slug) => typeof slug === 'string' && slug))];
    } catch {
        return [];
    }
}

function persistDockedAppSlugs(slugs) {
    if (typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(DOCKED_APPS_KEY, JSON.stringify(slugs));
    } catch {
        // Docking still works for the session when localStorage is unavailable.
    }
}

/** Owns the shared App catalog and persistent sidebar docking preferences. */
export function CustomAppsProvider({ children }) {
    const { features, featuresLoaded } = useAppData();
    const enabled = Boolean(features.custom_apps);
    const catalog = useCustomAppsCatalog({ enabled });
    const [dockedAppSlugs, setDockedAppSlugs] = useState(readDockedAppSlugs);

    useEffect(() => {
        if (enabled) catalog.refresh();
    }, [catalog.refresh, enabled]);

    const dockApp = useCallback((slug) => {
        setDockedAppSlugs((current) => {
            if (!slug || current.includes(slug)) return current;
            const next = [...current, slug];
            persistDockedAppSlugs(next);
            return next;
        });
    }, []);

    const undockApp = useCallback((slug) => {
        setDockedAppSlugs((current) => {
            const next = current.filter((candidate) => candidate !== slug);
            if (next.length === current.length) return current;
            persistDockedAppSlugs(next);
            return next;
        });
    }, []);

    const reorderDockedApps = useCallback((orderedSlugs) => {
        setDockedAppSlugs((current) => {
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
            persistDockedAppSlugs(next);
            return next;
        });
    }, []);

    const value = useMemo(() => ({
        enabled,
        featureLoaded: featuresLoaded,
        catalog,
        dockedAppSlugs,
        dockApp,
        undockApp,
        reorderDockedApps,
    }), [
        catalog,
        dockApp,
        dockedAppSlugs,
        enabled,
        featuresLoaded,
        reorderDockedApps,
        undockApp,
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
