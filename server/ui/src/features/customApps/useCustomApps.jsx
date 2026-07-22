import { useCallback, useEffect, useRef } from 'react';

import useCustomAppsCatalog from './useCustomAppsCatalog.js';
import useCustomAppWorkspace from './useCustomAppWorkspace.jsx';

/**
 * Coordinates Custom Apps discovery, Home resolution, and the persistent app
 * workspace. Custom Apps deliberately remain outside URL routing for now.
 */
export default function useCustomApps({
    enabled,
    setupComplete,
    homeAppSlug,
    setHomeAppSlug,
    navigation,
    preview,
    setDraft,
    destinationKind,
}) {
    const initialHomeAppliedRef = useRef(false);
    const handleHomeAppChange = useCallback((slug) => {
        initialHomeAppliedRef.current = true;
        setHomeAppSlug(slug);
    }, [setHomeAppSlug]);

    const catalog = useCustomAppsCatalog({
        enabled,
        homeAppSlug,
        onHomeAppChange: handleHomeAppChange,
    });
    const workspace = useCustomAppWorkspace({
        preview,
        setDraft,
        navigation,
        homeAppSlug,
        onHomeAppChange: handleHomeAppChange,
    });

    useEffect(() => {
        if (initialHomeAppliedRef.current || setupComplete !== true) return;
        if (!enabled || !homeAppSlug) return;
        initialHomeAppliedRef.current = true;
        navigation.openHome();
    }, [enabled, homeAppSlug, navigation, setupComplete]);

    useEffect(() => {
        if (!enabled || !['apps', 'home'].includes(destinationKind)) return;
        catalog.refresh();
    }, [catalog.refresh, destinationKind, enabled]);

    useEffect(() => {
        if (destinationKind !== 'home' || !catalog.loaded) return;
        if (!homeAppSlug) {
            workspace.openApps();
            return;
        }
        const app = catalog.findBySlug(homeAppSlug);
        if (app) workspace.openHome(app);
    }, [
        catalog.findBySlug,
        catalog.loaded,
        destinationKind,
        homeAppSlug,
        workspace.openApps,
        workspace.openHome,
    ]);

    useEffect(() => {
        if (enabled) return;
        workspace.reset();
        if (['apps', 'home', 'workspace'].includes(destinationKind)) navigation.openChat();
    }, [destinationKind, enabled, navigation, workspace.reset]);

    return { catalog, workspace };
}
