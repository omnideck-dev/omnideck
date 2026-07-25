import {
    useCallback,
    useEffect,
    useState,
} from 'react';

import {
    useAppEffectSubscription,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    useCurrentNavigationTarget,
    useDesktopNavigationCommands,
} from '../navigation/DesktopNavigation.jsx';
import { DESKTOP_TAB_GROUP_IDS } from '../desktop/desktopLayoutReducer.js';
import {
    useDesktopViewCommands,
    useDesktopViewCatalog,
} from '../desktop/DesktopViewRuntime.jsx';
import { useCustomApps } from './CustomApps.jsx';
import {
    createCustomAppView,
    customAppSlugForView,
} from './customAppDesktopViews.js';

/**
 * Owns Custom App effects which outlive any one rendered app View.
 *
 * It deliberately returns no render data. Individual Custom App adapters read
 * their own domain contexts when they render.
 */
export default function useCustomAppDesktopViews({ openApp }) {
    const customApps = useCustomApps();
    const currentNavigationTarget = useCurrentNavigationTarget();
    const navigation = useDesktopNavigationCommands();
    const desktopModel = useDesktopViewCatalog();
    const desktopCommands = useDesktopViewCommands();
    const { loaded: catalogLoaded, findBySlug } = customApps.catalog;
    const [pendingAppSlug, setPendingAppSlug] = useState(null);
    const targetType = currentNavigationTarget?.kind || null;

    const reloadApp = useCallback((viewId) => {
        const view = desktopModel.openViewsById[viewId];
        if (!view?.actions?.some((action) => action.id === 'reload')) return;
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

    const handleOpenAppRequest = useCallback((effect) => {
        setPendingAppSlug(effect.appSlug || null);
    }, []);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.OPEN_CUSTOM_APP_REQUESTED,
        handleOpenAppRequest,
    );

    // A deep-linked slug is the Custom Apps domain's deferred state. Resolve
    // it once the catalog is authoritative, then clear it whether or not the
    // requested app still exists.
    useEffect(() => {
        if (!pendingAppSlug || !catalogLoaded) return;
        const app = findBySlug(pendingAppSlug);
        if (customApps.enabled && app) {
            // openView also focuses an existing instance, so a repeated deep
            // link is still a meaningful navigation command.
            openApp(app, DESKTOP_TAB_GROUP_IDS.LEFT);
        }
        setPendingAppSlug(null);
    }, [
        catalogLoaded,
        customApps.enabled,
        pendingAppSlug,
        findBySlug,
        openApp,
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
            const app = findBySlug(
                customAppSlugForView(view) || view.app?.slug,
            );
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
