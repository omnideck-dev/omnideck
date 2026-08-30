import { createContext, useContext } from 'react';

import useAgentProfiles from '../hooks/useAgentProfiles.js';
import useFeatures from '../hooks/useFeatures.js';
import useProviders from '../hooks/useProviders.js';
import useSkills from '../hooks/useSkills.js';
import useBrowserProfiles from '../features/browser/useBrowserProfiles.js';
import { BrowserProfilesCatalogProvider } from '../features/browser/BrowserProfilesContext.jsx';

/**
 * App-wide data that several panels need: agent profiles, Browser profiles,
 * providers, skills, and feature flags. Provided once at the app root so
 * callers don't have to prop-drill (or call the underlying hooks twice and
 * get separate copies of their state).
 */
const AppDataContext = createContext(null);

export function AppDataProvider({ children }) {
    const profilesHook = useAgentProfiles();
    const providersHook = useProviders();
    const skillsHook = useSkills();
    const browserProfilesHook = useBrowserProfiles();
    const {
        features,
        loaded: featuresLoaded,
        refresh: refreshFeatures,
    } = useFeatures();
    const value = {
        profilesHook,
        providersHook,
        skillsHook,
        browserProfilesHook,
        features,
        featuresLoaded,
        refreshFeatures,
    };
    return (
        <AppDataContext.Provider value={value}>
            <BrowserProfilesCatalogProvider value={browserProfilesHook}>
                {children}
            </BrowserProfilesCatalogProvider>
        </AppDataContext.Provider>
    );
}

/** Returns shared profile, provider, skill, and feature state. Throws outside the provider. */
export function useAppData() {
    const value = useContext(AppDataContext);
    if (value === null) {
        throw new Error('useAppData must be used inside <AppDataProvider>');
    }
    return value;
}
