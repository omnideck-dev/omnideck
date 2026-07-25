import { useCallback, useMemo, useReducer } from 'react';

import {
    createInitialDesktopLayoutState,
    DESKTOP_TAB_GROUP_IDS,
    desktopLayoutReducer,
} from './desktopLayoutReducer.js';

function tabGroupModel(tabGroup, openViewsById) {
    return {
        ...tabGroup,
        views: tabGroup.viewIds
            .map((viewId) => openViewsById[viewId])
            .filter(Boolean),
    };
}

/** Owns placement and focus across tab groups and floating views. */
export default function useDesktopLayout({
    initialView = null,
    initialLayoutState = null,
} = {}) {
    const [state, dispatch] = useReducer(
        desktopLayoutReducer,
        { initialView, initialLayoutState },
        ({ initialView: view, initialLayoutState: restoredState }) => (
            restoredState || createInitialDesktopLayoutState(view)
        ),
    );

    const openView = useCallback((view, tabGroupId, options = {}) => {
        dispatch({
            type: 'OPEN_VIEW',
            view,
            tabGroupId,
            activate: options.activate,
        });
    }, []);
    const updateViews = useCallback((views) => {
        dispatch({ type: 'UPDATE_VIEWS', views });
    }, []);
    const syncViews = useCallback(({ views = [], closeViewIds = [] }) => {
        dispatch({
            type: 'SYNC_VIEWS',
            views,
            closeViewIds,
        });
    }, []);
    const moveView = useCallback((viewId, tabGroupId) => {
        dispatch({ type: 'MOVE_VIEW', viewId, tabGroupId });
    }, []);
    const floatView = useCallback((viewId, bounds = null) => {
        dispatch({ type: 'FLOAT_VIEW', viewId, bounds });
    }, []);
    const focusFloatingView = useCallback((viewId) => {
        dispatch({ type: 'FOCUS_FLOATING_VIEW', viewId });
    }, []);
    const updateFloatingBounds = useCallback((viewId, bounds) => {
        dispatch({ type: 'UPDATE_FLOATING_BOUNDS', viewId, bounds });
    }, []);
    const selectView = useCallback((tabGroupId, viewId) => {
        dispatch({ type: 'SELECT_VIEW', tabGroupId, viewId });
    }, []);
    const closeView = useCallback((viewId) => {
        dispatch({
            type: 'CLOSE_VIEW',
            viewId,
        });
    }, []);
    const closeViews = useCallback((viewIds) => {
        dispatch({
            type: 'CLOSE_VIEWS',
            viewIds,
        });
    }, []);
    const setSplitRatio = useCallback((ratio) => {
        dispatch({ type: 'SET_SPLIT_RATIO', ratio });
    }, []);
    const enterFullscreen = useCallback((viewId) => {
        dispatch({ type: 'ENTER_FULLSCREEN', viewId });
    }, []);
    const setFullscreenView = useCallback((viewId) => {
        dispatch({ type: 'SET_FULLSCREEN_VIEW', viewId });
    }, []);

    const model = useMemo(() => ({
        tabGroups: {
            [DESKTOP_TAB_GROUP_IDS.LEFT]: tabGroupModel(
                state.tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT],
                state.openViewsById,
            ),
            [DESKTOP_TAB_GROUP_IDS.RIGHT]: tabGroupModel(
                state.tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT],
                state.openViewsById,
            ),
        },
        openViews: Object.values(state.openViewsById),
        openViewsById: state.openViewsById,
        floatingViews: Object.values(
            state.floatingByViewId || {},
        ),
        floatingByViewId: state.floatingByViewId || {},
        focusedTabGroupId: state.focusedTabGroupId,
        focusedFloatingViewId: state.focusedFloatingViewId || null,
        splitRatio: state.splitRatio,
        fullscreenViewId: state.fullscreenViewId,
    }), [state]);

    const commands = useMemo(() => ({
        openView,
        updateViews,
        syncViews,
        moveView,
        floatView,
        focusFloatingView,
        updateFloatingBounds,
        selectView,
        closeView,
        closeViews,
        setSplitRatio,
        enterFullscreen,
        setFullscreenView,
    }), [
        closeView,
        closeViews,
        enterFullscreen,
        floatView,
        focusFloatingView,
        moveView,
        openView,
        syncViews,
        updateViews,
        selectView,
        setSplitRatio,
        setFullscreenView,
        updateFloatingBounds,
    ]);

    return { model, commands };
}

export { DESKTOP_TAB_GROUP_IDS };
