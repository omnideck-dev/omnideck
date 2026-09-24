import {
    createContext,
    useCallback,
    useContext,
    useMemo,
    useState,
} from 'react';

import { useAppEffectSubscription } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';

const BrowserProfileLoadRequestContext = createContext(null);

/** Own the Browser domain's short-lived request to load a saved profile. */
export function BrowserProfileLoadRequestProvider({ children }) {
    const [request, setRequest] = useState(null);
    const handleRequest = useCallback((effect) => {
        if (!effect.payload.profileId) return;
        setRequest({
            profileId: effect.payload.profileId,
            profileName: effect.payload.profileName || '',
        });
    }, []);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.OPEN_BROWSER_PROFILE_REQUESTED,
        handleRequest,
    );
    const clearRequest = useCallback(() => setRequest(null), []);
    const value = useMemo(() => ({ request, clearRequest }), [clearRequest, request]);

    return (
        <BrowserProfileLoadRequestContext.Provider value={value}>
            {children}
        </BrowserProfileLoadRequestContext.Provider>
    );
}

export function useBrowserProfileLoadRequest() {
    const value = useContext(BrowserProfileLoadRequestContext);
    if (value === null) {
        throw new Error(
            'useBrowserProfileLoadRequest must be used within BrowserProfileLoadRequestProvider',
        );
    }
    return value;
}
