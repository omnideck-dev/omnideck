import { createContext, useContext } from 'react';

import useAgentProfiles from '../hooks/useAgentProfiles.js';
import useFeatures from '../hooks/useFeatures.js';

/**
 * App-wide data that several panels need: the agent-profiles store and
 * the feature-flags object. Provided once at the app root so callers
 * don't have to prop-drill (or call the underlying hooks twice and get
 * separate copies of their state).
 */
const AppDataContext = createContext(null);

export function AppDataProvider({ children }) {
    const profilesHook = useAgentProfiles();
    const {
        features,
        loaded: featuresLoaded,
        refresh: refreshFeatures,
    } = useFeatures();
    const value = {
        profilesHook,
        features,
        featuresLoaded,
        refreshFeatures,
    };
    return (
        <AppDataContext.Provider value={value}>
            {children}
        </AppDataContext.Provider>
    );
}

/** Returns shared profile and feature state. Throws if used outside the provider. */
export function useAppData() {
    const value = useContext(AppDataContext);
    if (value === null) {
        throw new Error('useAppData must be used inside <AppDataProvider>');
    }
    return value;
}
