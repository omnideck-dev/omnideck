import { useCallback, useMemo, useReducer } from 'react';

import {
    createInitialDesktopWindowState,
    DESKTOP_PANE_IDS,
    desktopWindowReducer,
} from './desktopWindowReducer.js';

function paneModel(pane, surfacesById) {
    return {
        ...pane,
        surfaces: pane.surfaceIds
            .map((surfaceId) => surfacesById[surfaceId])
            .filter(Boolean),
    };
}

/** Owns placement and focus across pane stacks and floating windows. */
export default function useDesktopWindowManager({
    initialSurface = null,
    initialWindowState = null,
} = {}) {
    const [state, dispatch] = useReducer(
        desktopWindowReducer,
        { initialSurface, initialWindowState },
        ({ initialSurface: surface, initialWindowState: restoredState }) => (
            restoredState || createInitialDesktopWindowState(surface)
        ),
    );

    const openSurface = useCallback((surface, paneId, options = {}) => {
        dispatch({
            type: 'OPEN_SURFACE',
            surface,
            paneId,
            activate: options.activate,
        });
    }, []);
    const registerSurfaces = useCallback((surfaces) => {
        dispatch({ type: 'REGISTER_SURFACES', surfaces });
    }, []);
    const reconcileSurfaceGroup = useCallback((group, surfaces, defaultPaneId = null) => {
        dispatch({
            type: 'RECONCILE_SURFACE_GROUP',
            group,
            surfaces,
            defaultPaneId,
        });
    }, []);
    const moveSurface = useCallback((surfaceId, paneId) => {
        dispatch({ type: 'MOVE_SURFACE', surfaceId, paneId });
    }, []);
    const floatSurface = useCallback((surfaceId, bounds = null) => {
        dispatch({ type: 'FLOAT_SURFACE', surfaceId, bounds });
    }, []);
    const focusFloatingSurface = useCallback((surfaceId) => {
        dispatch({ type: 'FOCUS_FLOATING_SURFACE', surfaceId });
    }, []);
    const updateFloatingBounds = useCallback((surfaceId, bounds) => {
        dispatch({ type: 'UPDATE_FLOATING_BOUNDS', surfaceId, bounds });
    }, []);
    const selectSurface = useCallback((paneId, surfaceId) => {
        dispatch({ type: 'SELECT_SURFACE', paneId, surfaceId });
    }, []);
    const closeSurface = useCallback((surfaceId) => {
        dispatch({
            type: 'CLOSE_SURFACE',
            surfaceId,
        });
    }, []);
    const requestSurfaceFocus = useCallback((surfaceId, paneId) => {
        if (!surfaceId) return;
        dispatch({
            type: 'REQUEST_SURFACE_FOCUS',
            surfaceId,
            paneId,
        });
    }, []);
    const setSplitRatio = useCallback((ratio) => {
        dispatch({ type: 'SET_SPLIT_RATIO', ratio });
    }, []);
    const enterFullscreen = useCallback((surfaceId) => {
        dispatch({ type: 'ENTER_FULLSCREEN', surfaceId });
    }, []);
    const setFullscreenSurface = useCallback((surfaceId) => {
        dispatch({ type: 'SET_FULLSCREEN_SURFACE', surfaceId });
    }, []);

    const model = useMemo(() => ({
        panes: {
            [DESKTOP_PANE_IDS.LEFT]: paneModel(
                state.panes[DESKTOP_PANE_IDS.LEFT],
                state.surfacesById,
            ),
            [DESKTOP_PANE_IDS.RIGHT]: paneModel(
                state.panes[DESKTOP_PANE_IDS.RIGHT],
                state.surfacesById,
            ),
        },
        surfaces: Object.values(state.surfacesById),
        surfacesById: state.surfacesById,
        floatingWindows: Object.values(
            state.floatingWindowsBySurfaceId || {},
        ),
        floatingWindowsBySurfaceId: state.floatingWindowsBySurfaceId || {},
        focusedPaneId: state.focusedPaneId,
        focusedFloatingSurfaceId: state.focusedFloatingSurfaceId || null,
        splitRatio: state.splitRatio,
        fullscreenSurfaceId: state.fullscreenSurfaceId,
        pendingFocus: state.pendingFocus,
    }), [state]);

    const commands = useMemo(() => ({
        openSurface,
        registerSurfaces,
        reconcileSurfaceGroup,
        moveSurface,
        floatSurface,
        focusFloatingSurface,
        updateFloatingBounds,
        selectSurface,
        closeSurface,
        requestSurfaceFocus,
        setSplitRatio,
        enterFullscreen,
        setFullscreenSurface,
    }), [
        closeSurface,
        enterFullscreen,
        floatSurface,
        focusFloatingSurface,
        moveSurface,
        openSurface,
        reconcileSurfaceGroup,
        registerSurfaces,
        requestSurfaceFocus,
        selectSurface,
        setSplitRatio,
        setFullscreenSurface,
        updateFloatingBounds,
    ]);

    return { model, commands };
}

export { DESKTOP_PANE_IDS };
