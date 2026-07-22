import {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useReducer,
} from 'react';

import { useAppData } from '../../contexts/AppData.jsx';
import { useAppSettings } from '../app/AppSettings.jsx';
import useCustomAppsCatalog from './useCustomAppsCatalog.js';

const INITIAL_STATE = {
    openApp: null,
    reloadSignal: 0,
    error: '',
};

function reducer(state, action) {
    switch (action.type) {
        case 'OPEN':
            return {
                openApp: action.app,
                reloadSignal: state.openApp?.slug === action.app.slug
                    ? state.reloadSignal
                    : 0,
                error: '',
            };
        case 'RELOAD':
            return { ...state, reloadSignal: state.reloadSignal + 1 };
        case 'ERROR':
            return { ...state, error: action.message };
        case 'CLOSE':
            return INITIAL_STATE;
        default:
            return state;
    }
}

const CustomAppsContext = createContext(null);

/** Owns Custom App discovery, identity, iframe reloads, Home, and errors. */
export function CustomAppsProvider({ children }) {
    const { features } = useAppData();
    const { homeAppSlug, setHomeAppSlug } = useAppSettings();
    const enabled = Boolean(features.custom_apps);
    const [state, dispatch] = useReducer(reducer, INITIAL_STATE);

    const catalog = useCustomAppsCatalog({
        enabled,
        homeAppSlug,
        onHomeAppChange: setHomeAppSlug,
    });

    useEffect(() => {
        if (enabled) catalog.refresh();
    }, [catalog.refresh, enabled]);

    useEffect(() => {
        if (!enabled) dispatch({ type: 'CLOSE' });
    }, [enabled]);

    const open = useCallback((app) => dispatch({ type: 'OPEN', app }), []);
    const close = useCallback(() => dispatch({ type: 'CLOSE' }), []);
    const reload = useCallback(() => dispatch({ type: 'RELOAD' }), []);

    const toggleHome = useCallback(async () => {
        if (!state.openApp) return false;
        dispatch({ type: 'ERROR', message: '' });
        const isHome = state.openApp.slug === homeAppSlug;
        try {
            const response = await fetch('/api/custom-apps/home', isHome
                ? { method: 'DELETE' }
                : {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slug: state.openApp.slug }),
                });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error?.message || 'Could not update Home app');
            setHomeAppSlug(body.home_app_slug || null);
            return true;
        } catch (error) {
            dispatch({ type: 'ERROR', message: error.message || 'Could not update Home app' });
            return false;
        }
    }, [homeAppSlug, setHomeAppSlug, state.openApp]);

    const clearUnavailableHome = useCallback(async () => {
        dispatch({ type: 'ERROR', message: '' });
        try {
            const response = await fetch('/api/custom-apps/home', { method: 'DELETE' });
            const body = await response.json();
            if (!response.ok) throw new Error(body.error?.message || 'Could not remove Home app');
            setHomeAppSlug(null);
            return true;
        } catch (error) {
            dispatch({ type: 'ERROR', message: error.message || 'Could not remove Home app' });
            return false;
        }
    }, [setHomeAppSlug]);

    const value = useMemo(() => ({
        enabled,
        catalog,
        openApp: state.openApp,
        isOpen: Boolean(state.openApp),
        isHome: Boolean(state.openApp && state.openApp.slug === homeAppSlug),
        reloadSignal: state.reloadSignal,
        error: state.error,
        open,
        close,
        reload,
        toggleHome,
        clearUnavailableHome,
    }), [
        catalog,
        clearUnavailableHome,
        close,
        enabled,
        homeAppSlug,
        open,
        reload,
        state.error,
        state.openApp,
        state.reloadSignal,
        toggleHome,
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
