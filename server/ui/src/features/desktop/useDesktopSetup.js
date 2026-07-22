import { useCallback, useEffect, useState } from 'react';

/** Loads the settings required before the desktop can choose its first surface. */
export default function useDesktopSetup() {
    const [setupComplete, setSetupComplete] = useState(null);
    const [defaultProfileId, setDefaultProfileId] = useState(null);
    const [homeAppSlug, setHomeAppSlug] = useState(null);

    useEffect(() => {
        fetch('/api/settings')
            .then((response) => response.json())
            .then((settings) => {
                setSetupComplete(settings.setup_complete || false);
                if (settings.default_agent) setDefaultProfileId(settings.default_agent);
                if (settings.home_app_slug) setHomeAppSlug(settings.home_app_slug);
            })
            .catch(() => setSetupComplete(false));
    }, []);

    const finishSetup = useCallback(() => setSetupComplete(true), []);

    return {
        setupComplete,
        finishSetup,
        defaultProfileId,
        homeAppSlug,
        setHomeAppSlug,
    };
}
