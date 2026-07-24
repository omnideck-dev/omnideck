import { useCallback, useEffect } from 'react';

import { createCustomAppSurface } from './desktopSurfaces.js';
import { DESKTOP_PANE_IDS } from './desktopWindowReducer.js';

function customAppSurfaceId(slug) {
    return `custom-app:${slug}`;
}

/**
 * Adapts Custom App catalog choices and bridge messages to generic surfaces.
 *
 * Each app surface owns its app identity and reload revision. The shared
 * Custom Apps provider remains a catalog rather than a global "open app".
 */
export default function useCustomAppSurfaceController({
    customApps,
    destination,
    windowManager,
    navigation,
    setDraft,
}) {
    const { loaded: catalogLoaded, findBySlug } = customApps.catalog;
    const view = destination.kind;

    const openApp = useCallback((app, paneId = DESKTOP_PANE_IDS.LEFT) => {
        const existing = windowManager.model.surfacesById[
            customAppSurfaceId(app.slug)
        ];
        windowManager.commands.openSurface(
            createCustomAppSurface(app, existing?.reloadSignal || 0),
            paneId,
        );
        navigation.openCustomApp(app.slug);
    }, [
        navigation,
        windowManager.commands.openSurface,
        windowManager.model.surfacesById,
    ]);

    const reloadApp = useCallback((surfaceId) => {
        const surface = windowManager.model.surfacesById[surfaceId];
        if (surface?.kind !== 'custom-app') return;
        windowManager.commands.registerSurfaces([{
            ...surface,
            reloadSignal: (surface.reloadSignal || 0) + 1,
        }]);
    }, [
        windowManager.commands.registerSurfaces,
        windowManager.model.surfacesById,
    ]);

    const openChatFromApp = useCallback(() => {
        navigation.openChat();
    }, [navigation]);

    const composeFromApp = useCallback((surface, { text, context }) => {
        let addition = text.trim();
        if (context !== null && context !== undefined) {
            try {
                const serialized = JSON.stringify(context, null, 2).slice(0, 12000);
                addition += `${addition ? '\n\n' : ''}Context from ${surface.app.title}:\n${serialized}`;
            } catch {
                // Keep the authored text when optional context cannot be serialized.
            }
        }
        if (addition) {
            setDraft((current) => current.trim() ? `${current}\n\n${addition}` : addition);
        }
        openChatFromApp(surface);
    }, [openChatFromApp, setDraft]);

    useEffect(() => {
        if (view !== 'custom-app' || !catalogLoaded || !destination.appSlug) return;
        const surfaceId = customAppSurfaceId(destination.appSlug);
        if (windowManager.model.surfacesById[surfaceId]) return;
        const app = findBySlug(destination.appSlug);
        if (app) openApp(app, DESKTOP_PANE_IDS.LEFT);
    }, [
        catalogLoaded,
        destination.appSlug,
        findBySlug,
        openApp,
        view,
        windowManager.model.surfacesById,
    ]);

    useEffect(() => {
        if (!customApps.featureLoaded || customApps.enabled) return;
        windowManager.commands.reconcileSurfaceGroup('custom-app', []);
        if (['apps', 'custom-app'].includes(view)) navigation.openChat();
    }, [
        customApps.enabled,
        customApps.featureLoaded,
        navigation,
        view,
        windowManager.commands.reconcileSurfaceGroup,
    ]);

    useEffect(() => {
        if (!customApps.enabled || !catalogLoaded) return;
        const currentSurfaces = windowManager.model.surfaces.filter(
            (surface) => surface.kind === 'custom-app',
        );
        if (!currentSurfaces.length) return;

        let changed = false;
        const reconciledSurfaces = currentSurfaces.flatMap((surface) => {
            const app = findBySlug(surface.resourceId || surface.app?.slug);
            if (!app) {
                changed = true;
                return [];
            }
            if (surface.app === app) return [surface];
            changed = true;
            return [createCustomAppSurface(app, surface.reloadSignal || 0)];
        });
        if (changed) {
            windowManager.commands.reconcileSurfaceGroup(
                'custom-app',
                reconciledSurfaces,
            );
        }
    }, [
        catalogLoaded,
        customApps.enabled,
        findBySlug,
        windowManager.commands.reconcileSurfaceGroup,
        windowManager.model.surfaces,
    ]);

    return {
        openApp,
        reloadApp,
        openChatFromApp,
        composeFromApp,
    };
}
