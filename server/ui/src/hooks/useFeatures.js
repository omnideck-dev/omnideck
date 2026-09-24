import { useCallback, useEffect, useState } from 'react';

// Start gated features disabled so controls never flash before discovery
// completes, and remain hidden if the request fails.
const DEFAULTS = {
    image_generation: false,
    music_generation: false,
    desktop: false,
    visual_grounding: false,
    custom_tools: false,
    custom_apps: false,
};

/**
 * Fetch feature flags from the server and expose a refresh function for
 * settings-backed flags that can change while the shell is open.
 */
export default function useFeatures() {
    const [features, setFeatures] = useState(DEFAULTS);
    const [loaded, setLoaded] = useState(false);

    const refresh = useCallback(async () => {
        try {
            const res = await fetch('/api/features');
            if (res.ok) setFeatures(await res.json());
        } catch {
            // keep the last known feature state on error
        } finally {
            setLoaded(true);
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    return { features, loaded, refresh };
}
