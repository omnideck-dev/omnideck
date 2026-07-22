import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from 'react';

const AppSettingsContext = createContext(null);

/** Settings needed before the desktop can choose its initial surface. */
export function AppSettingsProvider({ children }) {
    const [setupComplete, setSetupComplete] = useState(null);
    const [defaultProfileId, setDefaultProfileId] = useState(null);
    const [homeAppSlug, setHomeAppSlug] = useState(null);

    useEffect(() => {
        let cancelled = false;
        fetch('/api/settings')
            .then((response) => response.json())
            .then((settings) => {
                if (cancelled) return;
                setSetupComplete(settings.setup_complete || false);
                setDefaultProfileId(settings.default_agent || null);
                setHomeAppSlug(settings.home_app_slug || null);
            })
            .catch(() => {
                if (!cancelled) setSetupComplete(false);
            });
        return () => { cancelled = true; };
    }, []);

    const finishSetup = useCallback(() => setSetupComplete(true), []);
    const value = useMemo(() => ({
        setupComplete,
        finishSetup,
        defaultProfileId,
        homeAppSlug,
        setHomeAppSlug,
    }), [defaultProfileId, finishSetup, homeAppSlug, setupComplete]);

    return (
        <AppSettingsContext.Provider value={value}>
            {children}
        </AppSettingsContext.Provider>
    );
}

export function useAppSettings() {
    const value = useContext(AppSettingsContext);
    if (value === null) {
        throw new Error('useAppSettings must be used within AppSettingsProvider');
    }
    return value;
}
