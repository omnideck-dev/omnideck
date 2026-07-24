export const DESKTOP_PANE_IDS = {
    LEFT: 'left',
    RIGHT: 'right',
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
        focusedPaneId: initialSurface ? DESKTOP_PANE_IDS.LEFT : null,
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
 * Generic presentation state for two equivalent surface stacks.
 *
 * Feature data and React content remain with their feature owners. This state
 * contains only serializable surface descriptions, placement, selection,
 * focus, split sizing, and full-screen presentation.
 */
export function desktopWindowReducer(state, action) {
    switch (action.type) {
        case 'OPEN_SURFACE': {
            const surfacesById = registerSurfaces(
                state.surfacesById,
                [action.surface],
            );
            const existingPaneId = paneContainingSurface(
                state.panes,
                action.surface.id,
            );
            const paneId = existingPaneId || action.paneId;
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
            for (const surfaceId of removedIds) {
                panes = removeSurfaceFromPanes(panes, surfaceId);
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
            return {
                ...state,
                surfacesById,
                fullscreenSurfaceId: removedIds.includes(state.fullscreenSurfaceId)
                    ? null
                    : state.fullscreenSurfaceId,
                ...pending,
            };
        }

        case 'MOVE_SURFACE':
            if (!state.surfacesById[action.surfaceId]) return state;
            return {
                ...state,
                panes: addSurfaceToPane(
                    state.panes,
                    action.paneId,
                    action.surfaceId,
                ),
                focusedPaneId: action.paneId,
            };

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
            };
        }

        case 'CLOSE_SURFACE': {
            if (!state.surfacesById[action.surfaceId]) return state;
            const surfacesById = { ...state.surfacesById };
            delete surfacesById[action.surfaceId];
            const panes = removeSurfaceFromPanes(state.panes, action.surfaceId);
            const focusedPane = state.focusedPaneId
                ? panes[state.focusedPaneId]
                : null;
            const focusedPaneId = focusedPane?.activeSurfaceId
                ? state.focusedPaneId
                : (
                    panes[DESKTOP_PANE_IDS.LEFT].activeSurfaceId
                        ? DESKTOP_PANE_IDS.LEFT
                        : (
                            panes[DESKTOP_PANE_IDS.RIGHT].activeSurfaceId
                                ? DESKTOP_PANE_IDS.RIGHT
                                : null
                        )
                );
            return {
                ...state,
                panes,
                surfacesById,
                focusedPaneId,
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
            return {
                ...state,
                panes: addSurfaceToPane(
                    state.panes,
                    action.paneId,
                    action.surfaceId,
                ),
                focusedPaneId: action.paneId,
                pendingFocus: null,
            };
        }

        case 'SET_SPLIT_RATIO':
            return { ...state, splitRatio: action.ratio };

        case 'ENTER_FULLSCREEN': {
            const paneId = paneContainingSurface(state.panes, action.surfaceId);
            if (!paneId || !state.surfacesById[action.surfaceId]) return state;
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
                fullscreenSurfaceId: action.surfaceId,
            };
        }

        case 'SET_FULLSCREEN_SURFACE':
            if (
                action.surfaceId !== null
                && !state.surfacesById[action.surfaceId]
            ) {
                return state;
            }
            return { ...state, fullscreenSurfaceId: action.surfaceId };

        default:
            return state;
    }
}
