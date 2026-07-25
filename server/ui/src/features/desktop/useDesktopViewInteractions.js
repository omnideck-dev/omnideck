import { useCallback, useMemo } from 'react';

import { useAppEffectDispatch } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import { createDesktopViewActions } from './desktopViewActions.js';

/**
 * Coordinates generic View gestures and lifecycle effects.
 *
 * Selection and placement mutate Desktop Layout directly. The focused View is
 * therefore also the application location; no navigation writeback is needed.
 */
export default function useDesktopViewInteractions({
    desktopLayout,
}) {
    const dispatchAppEffect = useAppEffectDispatch();
    const { model, commands } = desktopLayout;

    const handleSelectView = useCallback((tabGroupId, viewId) => {
        commands.selectView(tabGroupId, viewId);
    }, [commands.selectView]);

    const closeManagedViews = useCallback((views) => {
        if (!views.length) return;
        // Effect delivery is synchronous, so feature cascades observe the
        // descriptors before layout removes them.
        dispatchAppEffect({
            type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
            payload: { views },
        });
        commands.closeViews(views.map((view) => view.id));
    }, [commands.closeViews, dispatchAppEffect]);

    const handleCloseView = useCallback((tabGroupId, viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        closeManagedViews([view]);
    }, [closeManagedViews, model.openViewsById]);

    const handleMoveView = useCallback((viewId, targetTabGroupId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.moveView(viewId, targetTabGroupId);
    }, [commands.moveView, model.openViewsById]);

    const handleFloatView = useCallback((viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.floatView(viewId);
    }, [commands.floatView, model.openViewsById]);

    const handleEnterFullscreen = useCallback((viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.enterFullscreen(viewId);
    }, [commands.enterFullscreen, model.openViewsById]);

    const closeViewBatch = useCallback((
        tabGroupId,
        viewIds,
        activateViewId = null,
    ) => {
        const views = [...new Set(viewIds)]
            .map((viewId) => model.openViewsById[viewId])
            .filter((view) => view && view.closable !== false);
        closeManagedViews(views);

        const activatedView = activateViewId
            ? model.openViewsById[activateViewId]
            : null;
        if (activatedView) {
            commands.selectView(tabGroupId, activateViewId);
        }
    }, [
        closeManagedViews,
        commands.selectView,
        model.openViewsById,
    ]);

    const handleCloseOtherViews = useCallback((tabGroupId, keepViewId) => {
        const tabGroup = model.tabGroups[tabGroupId];
        const viewIds = tabGroup.viewIds.filter(
            (viewId) => (
                viewId !== keepViewId
                && model.openViewsById[viewId]?.closable !== false
            ),
        );
        closeViewBatch(tabGroupId, viewIds, keepViewId);
    }, [closeViewBatch, model.openViewsById, model.tabGroups]);

    const handleCloseViewsToRight = useCallback((tabGroupId, viewId) => {
        const tabGroup = model.tabGroups[tabGroupId];
        const viewIndex = tabGroup.viewIds.indexOf(viewId);
        if (viewIndex < 0) return;
        const viewIds = tabGroup.viewIds
            .slice(viewIndex + 1)
            .filter(
                (candidateId) => (
                    model.openViewsById[candidateId]?.closable !== false
                ),
            );
        const activateViewId = viewIds.includes(tabGroup.activeViewId)
            ? viewId
            : null;
        closeViewBatch(tabGroupId, viewIds, activateViewId);
    }, [closeViewBatch, model.openViewsById, model.tabGroups]);

    const viewActionCommands = useMemo(() => ({
        moveView: handleMoveView,
        floatView: handleFloatView,
        enterFullscreen: handleEnterFullscreen,
        requestViewAction: (actionId, view) => dispatchAppEffect({
            type: APP_EFFECT_TYPES.DESKTOP_VIEW_ACTION_REQUESTED,
            payload: {
                actionId,
                view,
            },
        }),
        closeView: handleCloseView,
        closeOtherViews: handleCloseOtherViews,
        closeViewsToRight: handleCloseViewsToRight,
    }), [
        dispatchAppEffect,
        handleCloseOtherViews,
        handleCloseView,
        handleCloseViewsToRight,
        handleEnterFullscreen,
        handleFloatView,
        handleMoveView,
    ]);
    const getViewActions = useCallback((view, tabGroupId, options = {}) => (
        createDesktopViewActions({
            view,
            tabGroupId,
            tabGroup: tabGroupId ? model.tabGroups[tabGroupId] : null,
            floating: options.floating,
            commands: viewActionCommands,
        })
    ), [model.tabGroups, viewActionCommands]);

    return {
        getViewActions,
        handleCloseView,
        handleSelectView,
    };
}
