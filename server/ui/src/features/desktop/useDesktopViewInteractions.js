import { useCallback, useMemo } from 'react';

import { useAppEffectDispatch } from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';
import {
    focusOrderedVisibleViews,
    nextActiveViewIdAfterClose,
} from './desktopLayoutSelectors.js';
import { createDesktopViewActions } from './desktopViewActions.js';

/**
 * Coordinates generic View gestures with application navigation.
 *
 * This hook understands placement, selection, and navigationTarget only. It
 * announces lifecycle/action events so feature owners can apply domain policy.
 */
export default function useDesktopViewInteractions({
    desktopLayout,
    navigation,
}) {
    const dispatchAppEffect = useAppEffectDispatch();
    const { model, commands } = desktopLayout;

    const handleSelectView = useCallback((tabGroupId, viewId) => {
        commands.selectView(tabGroupId, viewId);
        const view = model.openViewsById[viewId];
        if (view?.navigationTarget) {
            navigation.openTarget(view.navigationTarget);
        }
    }, [commands.selectView, model.openViewsById, navigation]);

    const closeManagedViews = useCallback((views) => {
        if (!views.length) return;
        // Effect delivery is synchronous, so feature cascades observe the
        // descriptors before layout removes them.
        dispatchAppEffect({
            type: APP_EFFECT_TYPES.DESKTOP_VIEWS_CLOSING,
            views,
        });
        commands.closeViews(views.map((view) => view.id));
    }, [commands.closeViews, dispatchAppEffect]);

    const handleCloseView = useCallback((tabGroupId, viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        const wasActive = Boolean(
            tabGroupId
            && model.tabGroups[tabGroupId]?.activeViewId === viewId,
        );
        const fallback = wasActive
            ? model.openViewsById[
                nextActiveViewIdAfterClose(
                    model.tabGroups[tabGroupId],
                    viewId,
                )
            ]
            : null;
        const floatingFallback = !tabGroupId && view.navigationTarget
            ? focusOrderedVisibleViews(model, viewId)
                .find((candidate) => candidate.navigationTarget)
            : null;

        closeManagedViews([view]);

        if (wasActive && fallback?.navigationTarget) {
            navigation.openTarget(fallback.navigationTarget);
        } else if (!wasActive && floatingFallback?.navigationTarget) {
            navigation.openTarget(floatingFallback.navigationTarget);
        }
    }, [closeManagedViews, model, navigation]);

    const handleMoveView = useCallback((viewId, targetTabGroupId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.moveView(viewId, targetTabGroupId);
        if (view.navigationTarget) {
            navigation.openTarget(view.navigationTarget);
        }
    }, [commands.moveView, model.openViewsById, navigation]);

    const handleFloatView = useCallback((viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.floatView(viewId);
        if (view.navigationTarget) {
            navigation.openTarget(view.navigationTarget);
        }
    }, [commands.floatView, model.openViewsById, navigation]);

    const handleFocusView = useCallback((viewId) => {
        const view = model.openViewsById[viewId];
        if (view?.navigationTarget) {
            navigation.openTarget(view.navigationTarget);
        }
    }, [model.openViewsById, navigation]);

    const handleEnterFullscreen = useCallback((viewId) => {
        const view = model.openViewsById[viewId];
        if (!view) return;
        commands.enterFullscreen(viewId);
        if (view.navigationTarget) {
            navigation.openTarget(view.navigationTarget);
        }
    }, [commands.enterFullscreen, model.openViewsById, navigation]);

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
            if (activatedView.navigationTarget) {
                navigation.openTarget(activatedView.navigationTarget);
            }
        }
    }, [
        closeManagedViews,
        commands.selectView,
        model.openViewsById,
        navigation,
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
            actionId,
            view,
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
        handleFocusView,
        handleSelectView,
    };
}
