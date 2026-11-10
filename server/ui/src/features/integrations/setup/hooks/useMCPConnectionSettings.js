import { useEffect, useState } from 'react';
import { getMCPConnectionSettings } from '../../api/integrationsApi.js';

export default function useMCPConnectionSettings(connectionId) {
    const [settings, setSettings] = useState(null);
    const [error, setError] = useState(null);
    useEffect(() => {
        let cancelled = false;
        setSettings(null);
        setError(null);
        getMCPConnectionSettings(connectionId).then(value => {
            if (!cancelled) setSettings(value);
        }).catch(() => {
            if (!cancelled) setError('Close setup and try again.');
        });
        return () => { cancelled = true; };
    }, [connectionId]);
    return { settings, error };
}
