export const DESKTOP_PANE_IDS = {
    LEFT: 'left',
    RIGHT: 'right',
};

export const DEFAULT_FLOATING_WINDOW_BOUNDS = {
    x: 56,
    y: 48,
    width: 720,
    height: 480,
};

function emptyPane() {
    return {
        surfaceIds: [],
        activeSurfaceId: null,
    };
}

export function createInitialDesktopWindowState(initialSurface = null) {
    return {
        panes: {
            [DESKTOP_PANE_IDS.LEFT]: initialSurface
                ? {
                    surfaceIds: [initialSurface.id],
                    activeSurfaceId: initialSurface.id,
                }
                : emptyPane(),
            [DESKTOP_PANE_IDS.RIGHT]: emptyPane(),
        },
        surfacesById: initialSurface
            ? { [initialSurface.id]: initialSurface }
            : {},
        floatingWindowsBySurfaceId: {},
        focusedPaneId: initialSurface ? DESKTOP_PANE_IDS.LEFT : null,
        focusedFloatingSurfaceId: null,
        floatingZCounter: 0,
        splitRatio: 50,
        fullscreenSurfaceId: null,
        pendingFocus: null,
    };
}

export const INITIAL_DESKTOP_WINDOW_STATE = createInitialDesktopWindowState();

function withoutSurface(pane, surfaceId) {
    const index = pane.surfaceIds.indexOf(surfaceId);
    if (index === -1) return pane;
    const surfaceIds = pane.surfaceIds.filter((id) => id !== surfaceId);
    const activeSurfaceId = pane.activeSurfaceId === surfaceId
        ? (surfaceIds[index] || surfaceIds[index - 1] || null)
        : pane.activeSurfaceId;
    return { surfaceIds, activeSurfaceId };
}

function removeSurfaceFromPanes(panes, surfaceId) {
    return {
        [DESKTOP_PANE_IDS.LEFT]: withoutSurface(
            panes[DESKTOP_PANE_IDS.LEFT],
            surfaceId,
        ),
        [DESKTOP_PANE_IDS.RIGHT]: withoutSurface(
            panes[DESKTOP_PANE_IDS.RIGHT],
            surfaceId,
        ),
    };
}

function paneContainingSurface(panes, surfaceId) {
    return Object.values(DESKTOP_PANE_IDS).find(
        (paneId) => panes[paneId].surfaceIds.includes(surfaceId),
    ) || null;
}

function floatingWindowForSurface(state, surfaceId) {
    return state.floatingWindowsBySurfaceId?.[surfaceId] || null;
}

function surfaceIsPlaced(state, surfaceId) {
    return Boolean(
        paneContainingSurface(state.panes, surfaceId)
        || floatingWindowForSurface(state, surfaceId),
    );
}

function focusedPaneWithContent(panes, preferredPaneId) {
    if (preferredPaneId && panes[preferredPaneId]?.activeSurfaceId) {
        return preferredPaneId;
    }
    if (panes[DESKTOP_PANE_IDS.LEFT].activeSurfaceId) {
        return DESKTOP_PANE_IDS.LEFT;
    }
    if (panes[DESKTOP_PANE_IDS.RIGHT].activeSurfaceId) {
        return DESKTOP_PANE_IDS.RIGHT;
    }
    return null;
}

function withoutFloatingWindow(floatingWindowsBySurfaceId, surfaceId) {
    if (!floatingWindowsBySurfaceId?.[surfaceId]) {
        return floatingWindowsBySurfaceId || {};
    }
    const next = { ...floatingWindowsBySurfaceId };
    delete next[surfaceId];
    return next;
}

function defaultFloatingBounds(state) {
    const offset = Object.keys(state.floatingWindowsBySurfaceId || {}).length * 24;
    return {
        ...DEFAULT_FLOATING_WINDOW_BOUNDS,
        x: DEFAULT_FLOATING_WINDOW_BOUNDS.x + offset,
        y: DEFAULT_FLOATING_WINDOW_BOUNDS.y + offset,
    };
}

function nextFloatingWindow(state, surfaceId, bounds = null) {
    const zIndex = (state.floatingZCounter || 0) + 1;
    return {
        surfaceId,
        ...(floatingWindowForSurface(state, surfaceId)
            || defaultFloatingBounds(state)),
        ...(bounds || {}),
        zIndex,
    };
}

function addSurfaceToPane(panes, paneId, surfaceId, activate = true) {
    const currentPane = panes[paneId];
    if (currentPane.surfaceIds.includes(surfaceId)) {
        return {
            ...panes,
            [paneId]: {
                ...currentPane,
                activeSurfaceId: activate
                    ? surfaceId
                    : (currentPane.activeSurfaceId || surfaceId),
            },
        };
    }
    const without = removeSurfaceFromPanes(panes, surfaceId);
    const pane = without[paneId];
    const surfaceIds = [...pane.surfaceIds, surfaceId];
    return {
        ...without,
        [paneId]: {
            surfaceIds,
            activeSurfaceId: activate ? surfaceId : (pane.activeSurfaceId || surfaceId),
        },
    };
}

function registerSurfaces(surfacesById, surfaces) {
    if (!surfaces.length) return surfacesById;
    return surfaces.reduce(
        (registered, surface) => ({
            ...registered,
            [surface.id]: surface,
        }),
        surfacesById,
    );
}

function placePendingSurface(state, panes, surfacesById) {
    const pending = state.pendingFocus;
    if (!pending || !surfacesById[pending.surfaceId]) {
        return { panes, pendingFocus: pending, focusedPaneId: state.focusedPaneId };
    }
    return {
        panes: addSurfaceToPane(panes, pending.paneId, pending.surfaceId),
        pendingFocus: null,
        focusedPaneId: pending.paneId,
    };
}

/**
 * Generic presentation state for pane stacks and floating windows.
 *
 * Feature data and React content remain with their feature owners. This state
 * contains only serializable surface descriptions, placement, selection,
 * focus, split sizing, floating bounds, and full-screen presentation.
 */
export function desktopWindowReducer(state, action) {
    switch (action.type) {
        case 'OPEN_SURFACE': {
            const surfacesById = registerSurfaces(
                state.surfacesById,
                [action.surface],
            );
            if (floatingWindowForSurface(state, action.surface.id)) {
                if (action.activate === false) {
                    return {
                        ...state,
                        surfacesById,
                        pendingFocus: state.pendingFocus?.surfaceId === action.surface.id
                            ? null
                            : state.pendingFocus,
                    };
                }
                const floatingWindow = nextFloatingWindow(
                    state,
                    action.surface.id,
                );
                return {
                    ...state,
                    surfacesById,
                    floatingWindowsBySurfaceId: {
                        ...state.floatingWindowsBySurfaceId,
                        [action.surface.id]: floatingWindow,
                    },
                    focusedFloatingSurfaceId: action.surface.id,
                    floatingZCounter: floatingWindow.zIndex,
                    pendingFocus: state.pendingFocus?.surfaceId === action.surface.id
                        ? null
                        : state.pendingFocus,
                };
            }
            const existingPaneId = paneContainingSurface(
                state.panes,
                action.surface.id,
            );
            const paneId = existingPaneId
                || action.paneId
                || DESKTOP_PANE_IDS.LEFT;
            return {
                ...state,
                surfacesById,
                panes: addSurfaceToPane(
                    state.panes,
                    paneId,
                    action.surface.id,
                    action.activate !== false,
                ),
                focusedPaneId: action.activate === false
                    ? state.focusedPaneId
                    : paneId,
                focusedFloatingSurfaceId: action.activate === false
                    ? state.focusedFloatingSurfaceId
                    : null,
                pendingFocus: state.pendingFocus?.surfaceId === action.surface.id
                    ? null
                    : state.pendingFocus,
            };
        }

        case 'REGISTER_SURFACES': {
            const surfacesById = registerSurfaces(
                state.surfacesById,
                action.surfaces,
            );
            const pending = placePendingSurface(state, state.panes, surfacesById);
            return {
                ...state,
                surfacesById,
                ...pending,
            };
        }

        case 'RECONCILE_SURFACE_GROUP': {
            const nextIds = new Set(action.surfaces.map((surface) => surface.id));
            const removedIds = Object.values(state.surfacesById)
                .filter((surface) => surface.group === action.group && !nextIds.has(surface.id))
                .map((surface) => surface.id);
            let panes = state.panes;
            const surfacesById = { ...state.surfacesById };
            let floatingWindowsBySurfaceId = state.floatingWindowsBySurfaceId || {};
            for (const surfaceId of removedIds) {
                panes = removeSurfaceFromPanes(panes, surfaceId);
                floatingWindowsBySurfaceId = withoutFloatingWindow(
                    floatingWindowsBySurfaceId,
                    surfaceId,
                );
                delete surfacesById[surfaceId];
            }
            for (const surface of action.surfaces) {
                const isNew = !surfacesById[surface.id];
                surfacesById[surface.id] = surface;
                const isPlaced = Object.values(panes).some(
                    (pane) => pane.surfaceIds.includes(surface.id),
                );
                if (isNew && !isPlaced && action.defaultPaneId) {
                    panes = addSurfaceToPane(
                        panes,
                        action.defaultPaneId,
                        surface.id,
                        panes[action.defaultPaneId].activeSurfaceId === null,
                    );
                }
            }
            const pending = placePendingSurface(state, panes, surfacesById);
            const focusedPaneId = focusedPaneWithContent(
                pending.panes,
                pending.focusedPaneId,
            );
            return {
                ...state,
                surfacesById,
                floatingWindowsBySurfaceId,
                ...pending,
                focusedPaneId,
                focusedFloatingSurfaceId: removedIds.includes(
                    state.focusedFloatingSurfaceId,
                )
                    ? null
                    : state.focusedFloatingSurfaceId,
                fullscreenSurfaceId: removedIds.includes(state.fullscreenSurfaceId)
                    ? null
                    : state.fullscreenSurfaceId,
            };
        }

        case 'MOVE_SURFACE':
            if (!state.surfacesById[action.surfaceId]) return state;
            return {
                ...state,
                floatingWindowsBySurfaceId: withoutFloatingWindow(
                    state.floatingWindowsBySurfaceId,
                    action.surfaceId,
                ),
                panes: addSurfaceToPane(
                    state.panes,
                    action.paneId,
                    action.surfaceId,
                ),
                focusedPaneId: action.paneId,
                focusedFloatingSurfaceId: null,
            };

        case 'FLOAT_SURFACE': {
            if (!state.surfacesById[action.surfaceId]) return state;
            const panes = removeSurfaceFromPanes(state.panes, action.surfaceId);
            const floatingWindow = nextFloatingWindow(
                state,
                action.surfaceId,
                action.bounds,
            );
            return {
                ...state,
                panes,
                floatingWindowsBySurfaceId: {
                    ...(state.floatingWindowsBySurfaceId || {}),
                    [action.surfaceId]: floatingWindow,
                },
                focusedPaneId: focusedPaneWithContent(
                    panes,
                    state.focusedPaneId,
                ),
                focusedFloatingSurfaceId: action.surfaceId,
                floatingZCounter: floatingWindow.zIndex,
                pendingFocus: state.pendingFocus?.surfaceId === action.surfaceId
                    ? null
                    : state.pendingFocus,
            };
        }

        case 'FOCUS_FLOATING_SURFACE': {
            if (!floatingWindowForSurface(state, action.surfaceId)) return state;
            const floatingWindow = nextFloatingWindow(state, action.surfaceId);
            return {
                ...state,
                floatingWindowsBySurfaceId: {
                    ...state.floatingWindowsBySurfaceId,
                    [action.surfaceId]: floatingWindow,
                },
                focusedFloatingSurfaceId: action.surfaceId,
                floatingZCounter: floatingWindow.zIndex,
            };
        }

        case 'UPDATE_FLOATING_BOUNDS': {
            const current = floatingWindowForSurface(state, action.surfaceId);
            if (!current) return state;
            const bounds = action.bounds || {};
            const next = {
                ...current,
                ...(Number.isFinite(bounds.x) ? { x: Math.max(0, bounds.x) } : {}),
                ...(Number.isFinite(bounds.y) ? { y: Math.max(0, bounds.y) } : {}),
                ...(Number.isFinite(bounds.width)
                    ? { width: Math.max(320, bounds.width) }
                    : {}),
                ...(Number.isFinite(bounds.height)
                    ? { height: Math.max(220, bounds.height) }
                    : {}),
            };
            if (
                next.x === current.x
                && next.y === current.y
                && next.width === current.width
                && next.height === current.height
            ) {
                return state;
            }
            return {
                ...state,
                floatingWindowsBySurfaceId: {
                    ...state.floatingWindowsBySurfaceId,
                    [action.surfaceId]: next,
                },
            };
        }

        case 'SELECT_SURFACE': {
            const pane = state.panes[action.paneId];
            if (!pane.surfaceIds.includes(action.surfaceId)) return state;
            return {
                ...state,
                panes: {
                    ...state.panes,
                    [action.paneId]: {
                        ...pane,
                        activeSurfaceId: action.surfaceId,
                    },
                },
                focusedPaneId: action.paneId,
                focusedFloatingSurfaceId: null,
            };
        }

        case 'CLOSE_SURFACE': {
            if (!state.surfacesById[action.surfaceId]) return state;
            const surfacesById = { ...state.surfacesById };
            delete surfacesById[action.surfaceId];
            const panes = removeSurfaceFromPanes(state.panes, action.surfaceId);
            const focusedPaneId = focusedPaneWithContent(
                panes,
                state.focusedPaneId,
            );
            return {
                ...state,
                panes,
                surfacesById,
                floatingWindowsBySurfaceId: withoutFloatingWindow(
                    state.floatingWindowsBySurfaceId,
                    action.surfaceId,
                ),
                focusedPaneId,
                focusedFloatingSurfaceId: state.focusedFloatingSurfaceId === action.surfaceId
                    ? null
                    : state.focusedFloatingSurfaceId,
                pendingFocus: state.pendingFocus?.surfaceId === action.surfaceId
                    ? null
                    : state.pendingFocus,
                fullscreenSurfaceId: state.fullscreenSurfaceId === action.surfaceId
                    ? null
                    : state.fullscreenSurfaceId,
            };
        }

        case 'REQUEST_SURFACE_FOCUS': {
            const isRegistered = Boolean(state.surfacesById[action.surfaceId]);
            if (!isRegistered) {
                return {
                    ...state,
                    pendingFocus: {
                        surfaceId: action.surfaceId,
                        paneId: action.paneId,
                    },
                };
            }
            if (floatingWindowForSurface(state, action.surfaceId)) {
                const floatingWindow = nextFloatingWindow(state, action.surfaceId);
                return {
                    ...state,
                    floatingWindowsBySurfaceId: {
                        ...state.floatingWindowsBySurfaceId,
                        [action.surfaceId]: floatingWindow,
                    },
                    focusedFloatingSurfaceId: action.surfaceId,
                    floatingZCounter: floatingWindow.zIndex,
                    pendingFocus: null,
                };
            }
            return {
                ...state,
                panes: addSurfaceToPane(
                    state.panes,
                    action.paneId,
                    action.surfaceId,
                ),
                focusedPaneId: action.paneId,
                focusedFloatingSurfaceId: null,
                pendingFocus: null,
            };
        }

        case 'SET_SPLIT_RATIO':
            return { ...state, splitRatio: action.ratio };

        case 'ENTER_FULLSCREEN': {
            const paneId = paneContainingSurface(state.panes, action.surfaceId);
            const floating = floatingWindowForSurface(state, action.surfaceId);
            if (
                (!paneId && !floating)
                || !state.surfacesById[action.surfaceId]
            ) {
                return state;
            }
            if (floating) {
                return {
                    ...state,
                    focusedFloatingSurfaceId: action.surfaceId,
                    fullscreenSurfaceId: action.surfaceId,
                };
            }
            return {
                ...state,
                panes: {
                    ...state.panes,
                    [paneId]: {
                        ...state.panes[paneId],
                        activeSurfaceId: action.surfaceId,
                    },
                },
                focusedPaneId: paneId,
                focusedFloatingSurfaceId: null,
                fullscreenSurfaceId: action.surfaceId,
            };
        }

        case 'SET_FULLSCREEN_SURFACE':
            if (
                action.surfaceId !== null
                && (
                    !state.surfacesById[action.surfaceId]
                    || !surfaceIsPlaced(state, action.surfaceId)
                )
            ) {
                return state;
            }
            return { ...state, fullscreenSurfaceId: action.surfaceId };

        default:
            return state;
    }
}
