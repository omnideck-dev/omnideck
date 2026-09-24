import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useState,
} from 'react';

const AppSettingsContext = createContext(null);

/** Settings needed to complete setup and choose the default agent profile. */
export function AppSettingsProvider({ children }) {
    const [setupComplete, setSetupComplete] = useState(null);
    const [defaultProfileId, setDefaultProfileId] = useState(null);

    useEffect(() => {
        let cancelled = false;
        fetch('/api/settings')
            .then((response) => response.json())
            .then((settings) => {
                if (cancelled) return;
                setSetupComplete(settings.setup_complete || false);
                setDefaultProfileId(settings.default_agent || null);
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
    }), [defaultProfileId, finishSetup, setupComplete]);

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
