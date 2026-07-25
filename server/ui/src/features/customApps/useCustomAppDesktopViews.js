import { useCallback, useEffect } from 'react';

import {
    useAppEffectSubscription,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useDesktopNavigationCommands,
    useDesktopNavigationState,
} from '../navigation/DesktopNavigation.jsx';
import {
    createCustomAppView,
    customAppViewId,
} from '../desktop/desktopViews.js';
import { DESKTOP_TAB_GROUP_IDS } from '../desktop/desktopLayoutReducer.js';
import {
    useDesktopViewCommands,
    useDesktopViewCatalog,
} from '../desktop/DesktopViewRuntime.jsx';
import { useCustomApps } from './CustomApps.jsx';

/**
 * Open a catalog entry as a normal multi-instance Desktop View.
 *
 * This command is used by the Apps view and by URL-navigation reconciliation;
 * neither caller needs to know the Custom App View identity convention.
 */
export function useOpenCustomAppView() {
    const desktopModel = useDesktopViewCatalog();
    const desktopCommands = useDesktopViewCommands();
    const navigation = useDesktopNavigationCommands();

    return useCallback((
        app,
        tabGroupId = DESKTOP_TAB_GROUP_IDS.LEFT,
    ) => {
        const existing = desktopModel.openViewsById[customAppViewId(app.slug)];
        desktopCommands.openView(
            createCustomAppView(app, existing?.reloadSignal || 0),
            { tabGroupId },
        );
        navigation.openCustomApp(app.slug);
    }, [
        desktopCommands.openView,
        desktopModel.openViewsById,
        navigation,
    ]);
}

/**
 * Owns Custom App effects which outlive any one rendered app View.
 *
 * It deliberately returns no render data. Individual Custom App adapters read
 * their own domain contexts when they render.
 */
export default function useCustomAppDesktopViews() {
    const customApps = useCustomApps();
    const { navigationTarget } = useDesktopNavigationState();
    const navigation = useDesktopNavigationCommands();
    const desktopModel = useDesktopViewCatalog();
    const desktopCommands = useDesktopViewCommands();
    const openApp = useOpenCustomAppView();
    const { loaded: catalogLoaded, findBySlug } = customApps.catalog;
    const targetType = navigationTarget.kind;

    const reloadApp = useCallback((viewId) => {
        const view = desktopModel.openViewsById[viewId];
        if (!view?.actions?.includes('reload')) return;
        desktopCommands.updateViews([{
            ...view,
            reloadSignal: (view.reloadSignal || 0) + 1,
        }]);
    }, [
        desktopCommands.updateViews,
        desktopModel.openViewsById,
    ]);

    const handleViewAction = useCallback((effect) => {
        if (effect.actionId === 'reload') reloadApp(effect.view.id);
    }, [reloadApp]);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED,
        handleViewAction,
    );

    // A restored/deep-linked Custom App target is resolved after its catalog
    // has loaded. Desktop itself does not need to understand app slugs.
    useEffect(() => {
        if (
            targetType !== 'custom-app'
            || !catalogLoaded
            || !navigationTarget.appSlug
        ) return;
        const viewId = customAppViewId(navigationTarget.appSlug);
        if (desktopModel.openViewsById[viewId]) return;
        const app = findBySlug(navigationTarget.appSlug);
        if (app) openApp(app, DESKTOP_TAB_GROUP_IDS.LEFT);
    }, [
        catalogLoaded,
        navigationTarget.appSlug,
        findBySlug,
        openApp,
        targetType,
        desktopModel.openViewsById,
    ]);

    useEffect(() => {
        if (!customApps.featureLoaded || customApps.enabled) return;
        const customAppViewIds = desktopModel.openViews
            .filter((view) => view.type === 'custom-app')
            .map((view) => view.id);
        if (customAppViewIds.length) {
            desktopCommands.closeViews(customAppViewIds);
        }
        if (['apps', 'custom-app'].includes(targetType)) navigation.openChat();
    }, [
        customApps.enabled,
        customApps.featureLoaded,
        desktopCommands.closeViews,
        desktopModel.openViews,
        navigation,
        targetType,
    ]);

    // Persisted app descriptors are refreshed from the live catalog. Missing
    // apps disappear without making Desktop persistence understand catalogs.
    useEffect(() => {
        if (!customApps.enabled || !catalogLoaded) return;
        const currentViews = desktopModel.openViews.filter(
            (view) => view.type === 'custom-app',
        );
        if (!currentViews.length) return;

        let changed = false;
        const reconciledViews = currentViews.flatMap((view) => {
            const app = findBySlug(view.resourceId || view.app?.slug);
            if (!app) {
                changed = true;
                return [];
            }
            if (view.app === app) return [view];
            changed = true;
            return [createCustomAppView(app, view.reloadSignal || 0)];
        });
        if (changed) {
            const reconciledIds = new Set(
                reconciledViews.map((view) => view.id),
            );
            desktopCommands.syncViews({
                views: reconciledViews,
                closeViewIds: currentViews
                    .filter((view) => !reconciledIds.has(view.id))
                    .map((view) => view.id),
            });
        }
    }, [
        catalogLoaded,
        customApps.enabled,
        desktopCommands.syncViews,
        desktopModel.openViews,
        findBySlug,
    ]);
}
