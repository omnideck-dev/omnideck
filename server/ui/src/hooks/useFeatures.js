import { useCallback, useEffect, useState } from 'react';

const DEFAULTS = {
    image_generation: false,
    music_generation: false,
    desktop: false,
    visual_grounding: false,
    custom_tools: false,
    folder_apps: false,
};

/**
 * Fetch feature flags from the server and expose a refresh function for
 * settings-backed flags that can change while the shell is open.
 */
export default function useFeatures() {
    const [features, setFeatures] = useState(DEFAULTS);

    const refresh = useCallback(async () => {
        try {
            const res = await fetch('/api/features');
            if (!res.ok) return;
            setFeatures(await res.json());
        } catch {
            // keep the last known feature state on error
        }
    }, []);

    useEffect(() => {
        refresh();
    }, [refresh]);

    return { features, refresh };
}
