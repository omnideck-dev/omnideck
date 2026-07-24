import {
    createContext,
    useContext,
    useEffect,
    useMemo,
} from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import useCustomAppsCatalog from './useCustomAppsCatalog.js';

const CustomAppsContext = createContext(null);

/** Owns the shared Custom App catalog; open app instances belong to surfaces. */
export function CustomAppsProvider({ children }) {
    const { features, featuresLoaded } = useAppData();
    const enabled = Boolean(features.custom_apps);
    const catalog = useCustomAppsCatalog({ enabled });

    useEffect(() => {
        if (enabled) catalog.refresh();
    }, [catalog.refresh, enabled]);

    const value = useMemo(() => ({
        enabled,
        featureLoaded: featuresLoaded,
        catalog,
    }), [catalog, enabled, featuresLoaded]);

    return <CustomAppsContext.Provider value={value}>{children}</CustomAppsContext.Provider>;
}

export function useCustomApps() {
    const value = useContext(CustomAppsContext);
    if (value === null) {
        throw new Error('useCustomApps must be used within CustomAppsProvider');
    }
    return value;
}
