import {
    nextActiveViewIdAfterClose,
    tabGroupContainingView,
} from './desktopLayoutSelectors.js';

export const DESKTOP_TAB_GROUP_IDS = {
    LEFT: 'left',
    RIGHT: 'right',
};

export const DEFAULT_FLOATING_VIEW_BOUNDS = {
    x: 56,
    y: 48,
    width: 720,
    height: 480,
};
export const MIN_FLOATING_VIEW_WIDTH = 320;
export const MIN_FLOATING_VIEW_HEIGHT = 220;

/** Normalize persisted, restored, and live bounds with one shared policy. */
export function clampFloatingBounds(
    bounds,
    fallback = DEFAULT_FLOATING_VIEW_BOUNDS,
) {
    const numberOr = (value, fallbackValue) => (
        Number.isFinite(value) ? value : fallbackValue
    );
    return {
        x: Math.max(0, numberOr(bounds?.x, fallback.x)),
        y: Math.max(0, numberOr(bounds?.y, fallback.y)),
        width: Math.max(
            MIN_FLOATING_VIEW_WIDTH,
            numberOr(bounds?.width, fallback.width),
        ),
        height: Math.max(
            MIN_FLOATING_VIEW_HEIGHT,
            numberOr(bounds?.height, fallback.height),
        ),
    };
}

function emptyTabGroup() {
    return {
        viewIds: [],
        activeViewId: null,
    };
}

export function createInitialDesktopLayoutState(initialView = null) {
    return {
        tabGroups: {
            [DESKTOP_TAB_GROUP_IDS.LEFT]: initialView
                ? {
                    viewIds: [initialView.id],
                    activeViewId: initialView.id,
                }
                : emptyTabGroup(),
            [DESKTOP_TAB_GROUP_IDS.RIGHT]: emptyTabGroup(),
        },
        openViewsById: initialView
            ? { [initialView.id]: initialView }
            : {},
        floatingByViewId: {},
        focusedTabGroupId: initialView ? DESKTOP_TAB_GROUP_IDS.LEFT : null,
        focusedFloatingViewId: null,
        floatingZCounter: 0,
        splitRatio: 50,
        fullscreenViewId: null,
    };
}

export const INITIAL_DESKTOP_LAYOUT_STATE = createInitialDesktopLayoutState();

function withoutView(tabGroup, viewId) {
    if (!tabGroup.viewIds.includes(viewId)) return tabGroup;
    const viewIds = tabGroup.viewIds.filter((id) => id !== viewId);
    const activeViewId = tabGroup.activeViewId === viewId
        ? nextActiveViewIdAfterClose(tabGroup, viewId)
        : tabGroup.activeViewId;
    return { viewIds, activeViewId };
}

function removeViewFromTabGroups(tabGroups, viewId) {
    return {
        [DESKTOP_TAB_GROUP_IDS.LEFT]: withoutView(
            tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT],
            viewId,
        ),
        [DESKTOP_TAB_GROUP_IDS.RIGHT]: withoutView(
            tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT],
            viewId,
        ),
    };
}

function floatingViewForView(state, viewId) {
    return state.floatingByViewId?.[viewId] || null;
}

function viewIsPlaced(state, viewId) {
    return Boolean(
        tabGroupContainingView(state.tabGroups, viewId)
        || floatingViewForView(state, viewId),
    );
}

function focusedTabGroupWithContent(tabGroups, preferredTabGroupId) {
    if (preferredTabGroupId && tabGroups[preferredTabGroupId]?.activeViewId) {
        return preferredTabGroupId;
    }
    if (tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT].activeViewId) {
        return DESKTOP_TAB_GROUP_IDS.LEFT;
    }
    if (tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT].activeViewId) {
        return DESKTOP_TAB_GROUP_IDS.RIGHT;
    }
    return null;
}

function withoutFloatingView(floatingByViewId, viewId) {
    if (!floatingByViewId?.[viewId]) {
        return floatingByViewId || {};
    }
    const next = { ...floatingByViewId };
    delete next[viewId];
    return next;
}

function defaultFloatingBounds(state) {
    const offset = Object.keys(state.floatingByViewId || {}).length * 24;
    return {
        ...DEFAULT_FLOATING_VIEW_BOUNDS,
        x: DEFAULT_FLOATING_VIEW_BOUNDS.x + offset,
        y: DEFAULT_FLOATING_VIEW_BOUNDS.y + offset,
    };
}

function withFocusedFloating(state, viewId, bounds = null) {
    const ordered = Object.values(state.floatingByViewId || {})
        .filter((floatingView) => floatingView.viewId !== viewId)
        .sort((left, right) => left.zIndex - right.zIndex);
    const floatingByViewId = Object.fromEntries(
        ordered.map((floatingView, index) => [
            floatingView.viewId,
            { ...floatingView, zIndex: index + 1 },
        ]),
    );
    const current = floatingViewForView(state, viewId)
        || defaultFloatingBounds(state);
    const nextBounds = clampFloatingBounds(
        { ...current, ...(bounds || {}) },
        current,
    );
    const zIndex = ordered.length + 1;
    floatingByViewId[viewId] = {
        viewId,
        ...nextBounds,
        zIndex,
    };
    return {
        floatingByViewId,
        focusedFloatingViewId: viewId,
        floatingZCounter: zIndex,
    };
}

function addViewToTabGroup(tabGroups, tabGroupId, viewId, activate = true) {
    const currentTabGroup = tabGroups[tabGroupId];
    if (currentTabGroup.viewIds.includes(viewId)) {
        return {
            ...tabGroups,
            [tabGroupId]: {
                ...currentTabGroup,
                activeViewId: activate
                    ? viewId
                    : (currentTabGroup.activeViewId || viewId),
            },
        };
    }
    const without = removeViewFromTabGroups(tabGroups, viewId);
    const tabGroup = without[tabGroupId];
    const viewIds = [...tabGroup.viewIds, viewId];
    return {
        ...without,
        [tabGroupId]: {
            viewIds,
            activeViewId: activate ? viewId : (tabGroup.activeViewId || viewId),
        },
    };
}

function upsertViews(openViewsById, views) {
    if (!views.length) return openViewsById;
    return views.reduce(
        (current, view) => ({
            ...current,
            [view.id]: view,
        }),
        openViewsById,
    );
}

function syncViews(state, views, closeViewIds) {
    const closedIds = new Set(
        closeViewIds.filter((viewId) => state.openViewsById[viewId]),
    );
    if (closedIds.size === 0 && views.length === 0) return state;

    let tabGroups = state.tabGroups;
    let floatingByViewId = state.floatingByViewId || {};
    const openViewsById = { ...state.openViewsById };

    for (const viewId of closedIds) {
        tabGroups = removeViewFromTabGroups(tabGroups, viewId);
        floatingByViewId = withoutFloatingView(floatingByViewId, viewId);
        delete openViewsById[viewId];
    }
    for (const view of views) openViewsById[view.id] = view;

    const focusedTabGroupId = focusedTabGroupWithContent(
        tabGroups,
        state.focusedTabGroupId,
    );

    return {
        ...state,
        openViewsById,
        floatingByViewId,
        tabGroups,
        focusedTabGroupId,
        focusedFloatingViewId: closedIds.has(state.focusedFloatingViewId)
            ? null
            : state.focusedFloatingViewId,
        fullscreenViewId: closedIds.has(state.fullscreenViewId)
            ? null
            : state.fullscreenViewId,
    };
}

/**
 * Generic presentation state for tab groups and floating views.
 *
 * Domain data and React content remain with their domain owners. This state
 * contains only serializable view descriptions, placement, selection,
 * focus, split sizing, floating bounds, and full-screen presentation.
 */
export function desktopLayoutReducer(state, action) {
    switch (action.type) {
        case 'OPEN_VIEW': {
            const openViewsById = upsertViews(
                state.openViewsById,
                [action.view],
            );
            if (floatingViewForView(state, action.view.id)) {
                if (action.activate === false) {
                    return {
                        ...state,
                        openViewsById,
                    };
                }
                return {
                    ...state,
                    openViewsById,
                    ...withFocusedFloating(state, action.view.id),
                };
            }
            const existingTabGroupId = tabGroupContainingView(
                state.tabGroups,
                action.view.id,
            );
            const tabGroupId = existingTabGroupId
                || action.tabGroupId
                || DESKTOP_TAB_GROUP_IDS.LEFT;
            return {
                ...state,
                openViewsById,
                tabGroups: addViewToTabGroup(
                    state.tabGroups,
                    tabGroupId,
                    action.view.id,
                    action.activate !== false,
                ),
                focusedTabGroupId: action.activate === false
                    ? state.focusedTabGroupId
                    : tabGroupId,
                focusedFloatingViewId: action.activate === false
                    ? state.focusedFloatingViewId
                    : null,
            };
        }

        case 'UPDATE_VIEWS':
            return syncViews(state, action.views, []);

        case 'SYNC_VIEWS':
            return syncViews(
                state,
                action.views || [],
                action.closeViewIds || [],
            );

        case 'MOVE_VIEW':
            if (!state.openViewsById[action.viewId]) return state;
            return {
                ...state,
                floatingByViewId: withoutFloatingView(
                    state.floatingByViewId,
                    action.viewId,
                ),
                tabGroups: addViewToTabGroup(
                    state.tabGroups,
                    action.tabGroupId,
                    action.viewId,
                ),
                focusedTabGroupId: action.tabGroupId,
                focusedFloatingViewId: null,
            };

        case 'FLOAT_VIEW': {
            if (!state.openViewsById[action.viewId]) return state;
            const tabGroups = removeViewFromTabGroups(state.tabGroups, action.viewId);
            return {
                ...state,
                tabGroups,
                ...withFocusedFloating(
                    state,
                    action.viewId,
                    action.bounds,
                ),
                focusedTabGroupId: focusedTabGroupWithContent(
                    tabGroups,
                    state.focusedTabGroupId,
                ),
            };
        }

        case 'FOCUS_FLOATING_VIEW': {
            if (!floatingViewForView(state, action.viewId)) return state;
            return {
                ...state,
                ...withFocusedFloating(state, action.viewId),
            };
        }

        case 'UPDATE_FLOATING_BOUNDS': {
            const current = floatingViewForView(state, action.viewId);
            if (!current) return state;
            const next = {
                ...current,
                ...clampFloatingBounds({
                    ...current,
                    ...(action.bounds || {}),
                }, current),
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
                floatingByViewId: {
                    ...state.floatingByViewId,
                    [action.viewId]: next,
                },
            };
        }

        case 'SELECT_VIEW': {
            const tabGroup = state.tabGroups[action.tabGroupId];
            if (!tabGroup.viewIds.includes(action.viewId)) return state;
            return {
                ...state,
                tabGroups: {
                    ...state.tabGroups,
                    [action.tabGroupId]: {
                        ...tabGroup,
                        activeViewId: action.viewId,
                    },
                },
                focusedTabGroupId: action.tabGroupId,
                focusedFloatingViewId: null,
            };
        }

        case 'CLOSE_VIEW':
            if (!state.openViewsById[action.viewId]) return state;
            return syncViews(state, [], [action.viewId]);

        case 'CLOSE_VIEWS':
            return syncViews(state, [], action.viewIds || []);

        case 'SET_SPLIT_RATIO':
            return { ...state, splitRatio: action.ratio };

        case 'ENTER_FULLSCREEN': {
            const tabGroupId = tabGroupContainingView(state.tabGroups, action.viewId);
            const floating = floatingViewForView(state, action.viewId);
            if (
                (!tabGroupId && !floating)
                || !state.openViewsById[action.viewId]
            ) {
                return state;
            }
            if (floating) {
                return {
                    ...state,
                    focusedFloatingViewId: action.viewId,
                    fullscreenViewId: action.viewId,
                };
            }
            return {
                ...state,
                tabGroups: {
                    ...state.tabGroups,
                    [tabGroupId]: {
                        ...state.tabGroups[tabGroupId],
                        activeViewId: action.viewId,
                    },
                },
                focusedTabGroupId: tabGroupId,
                focusedFloatingViewId: null,
                fullscreenViewId: action.viewId,
            };
        }

        case 'SET_FULLSCREEN_VIEW':
            if (
                action.viewId !== null
                && (
                    !state.openViewsById[action.viewId]
                    || !viewIsPlaced(state, action.viewId)
                )
            ) {
                return state;
            }
            return { ...state, fullscreenViewId: action.viewId };

        default:
            return state;
    }
}
