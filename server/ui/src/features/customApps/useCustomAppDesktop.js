import { useCallback, useEffect, useRef } from 'react';

/** Applies desktop destinations to the open Custom App without owning app state. */
export default function useCustomAppDesktop({
    customApps,
    destination,
    dock,
    homeAppSlug,
    navigation,
    setDraft,
}) {
    const initialHomeAppliedRef = useRef(false);
    const view = destination.kind;
    const {
        loaded: catalogLoaded,
        findBySlug,
    } = customApps.catalog;

    const expandCustomApp = useCallback((app) => {
        customApps.open(app);
        dock.showCustomApp(app.slug);
        navigation.openCustomApp(app.slug);
    }, [customApps.open, dock.showCustomApp, navigation]);

    const openCustomAppInDock = useCallback((app) => {
        customApps.open(app);
        dock.showCustomApp(app.slug);
        navigation.openChat();
    }, [customApps.open, dock.showCustomApp, navigation]);

    const dockCustomApp = useCallback(() => {
        dock.showCustomApp(customApps.openApp?.slug);
        navigation.openChat();
    }, [customApps.openApp?.slug, dock.showCustomApp, navigation]);

    const closeCustomApp = useCallback(() => {
        customApps.close();
        if (view === 'custom-app') navigation.openChat();
    }, [customApps.close, navigation, view]);

    const openCustomApps = useCallback(() => navigation.openApps(), [navigation]);

    const clearUnavailableHome = useCallback(async () => {
        const cleared = await customApps.clearUnavailableHome();
        if (cleared) navigation.openApps();
    }, [customApps.clearUnavailableHome, navigation]);

    const toggleCustomAppHome = useCallback(async () => {
        const wasHome = customApps.isHome;
        const updated = await customApps.toggleHome();
        if (updated && wasHome) navigation.openApps();
    }, [customApps.isHome, customApps.toggleHome, navigation]);

    const openHome = useCallback(() => {
        const homeApp = homeAppSlug ? findBySlug(homeAppSlug) : null;
        if (homeApp) expandCustomApp(homeApp);
        else navigation.openHome();
    }, [expandCustomApp, findBySlug, homeAppSlug, navigation]);

    const composeFromCustomApp = useCallback(({ text, context }) => {
        const app = customApps.openApp;
        if (!app) return;
        let addition = text.trim();
        if (context !== null && context !== undefined) {
            try {
                const serialized = JSON.stringify(context, null, 2).slice(0, 12000);
                addition += `${addition ? '\n\n' : ''}Context from ${app.title}:\n${serialized}`;
            } catch {
                // Keep the authored text when optional context cannot be serialized.
            }
        }
        if (addition) {
            setDraft((current) => current.trim() ? `${current}\n\n${addition}` : addition);
        }
        dockCustomApp();
    }, [customApps.openApp, dockCustomApp, setDraft]);

    useEffect(() => {
        if (initialHomeAppliedRef.current || !customApps.enabled || !catalogLoaded) return;
        initialHomeAppliedRef.current = true;
        if (homeAppSlug) navigation.openHome();
    }, [catalogLoaded, customApps.enabled, homeAppSlug, navigation]);

    useEffect(() => {
        if (view !== 'home' || !catalogLoaded) return;
        if (!homeAppSlug) {
            navigation.openApps();
            return;
        }
        const homeApp = findBySlug(homeAppSlug);
        if (homeApp) expandCustomApp(homeApp);
    }, [catalogLoaded, expandCustomApp, findBySlug, homeAppSlug, navigation, view]);

    useEffect(() => {
        if (customApps.enabled) return;
        if (['apps', 'home', 'custom-app'].includes(view)) navigation.openChat();
    }, [customApps.enabled, navigation, view]);

    return {
        expandCustomApp,
        openCustomAppInDock,
        dockCustomApp,
        closeCustomApp,
        openCustomApps,
        openHome,
        clearUnavailableHome,
        toggleCustomAppHome,
        composeFromCustomApp,
    };
}
