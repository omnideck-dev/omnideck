import {
    clampFloatingBounds,
    DEFAULT_FLOATING_VIEW_BOUNDS,
    DESKTOP_TAB_GROUP_IDS,
} from './desktopLayoutReducer.js';
import {
    ARTIFACTS_VIEW_ID,
    validDesktopView,
} from './desktopViews.js';

// Keep the historical key so existing layouts can be migrated in place.
export const DESKTOP_LAYOUT_STORAGE_KEY = 'omnideck_desktop_window_v1';
const SNAPSHOT_VERSION = 3;
const PREVIOUS_SNAPSHOT_VERSION = 2;
const LEGACY_SNAPSHOT_VERSION = 1;
const TAB_GROUP_IDS = Object.values(DESKTOP_TAB_GROUP_IDS);

function isRecord(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function restoredViewId(viewId) {
    if (typeof viewId !== 'string') return viewId;
    const renamed = viewId.replace(
        /^conversation-execution:/,
        'workspace-resource:',
    );
    // Older snapshots could contain one Artifacts tab per conversation.
    // They now collapse into the single library View with a current filter.
    return renamed.startsWith(`${ARTIFACTS_VIEW_ID}:`)
        ? ARTIFACTS_VIEW_ID
        : renamed;
}

function restoredView(rawView) {
    if (!isRecord(rawView)) return rawView;
    return {
        ...rawView,
        id: restoredViewId(rawView.id),
    };
}

function migrateLegacyView(rawView) {
    if (!isRecord(rawView)) return rawView;
    const {
        kind,
        group: _group,
        id,
        destination,
        ...view
    } = rawView;
    return {
        ...view,
        id: restoredViewId(id),
        type: kind === 'conversation-execution'
            ? 'workspace-resource'
            : kind,
        ...(isRecord(destination)
            ? { navigationTarget: destination }
            : {}),
    };
}

function migrateLegacyTabGroup(rawPane) {
    const viewIds = Array.isArray(rawPane?.surfaceIds)
        ? rawPane.surfaceIds.map(restoredViewId)
        : [];
    return {
        viewIds,
        activeViewId: restoredViewId(rawPane?.activeSurfaceId) || null,
    };
}

function migrateLegacySnapshot(raw) {
    const legacyWindow = raw.window;
    if (!isRecord(legacyWindow) || !isRecord(legacyWindow.panes)) return null;
    const floatingViews = Array.isArray(legacyWindow.floatingWindows)
        ? legacyWindow.floatingWindows.map((floatingWindow) => {
            const { surfaceId, ...bounds } = floatingWindow;
            return {
                ...bounds,
                viewId: restoredViewId(surfaceId),
            };
        })
        : [];
    return {
        layout: {
            tabGroups: {
                [DESKTOP_TAB_GROUP_IDS.LEFT]: migrateLegacyTabGroup(
                    legacyWindow.panes[DESKTOP_TAB_GROUP_IDS.LEFT],
                ),
                [DESKTOP_TAB_GROUP_IDS.RIGHT]: migrateLegacyTabGroup(
                    legacyWindow.panes[DESKTOP_TAB_GROUP_IDS.RIGHT],
                ),
            },
            views: Array.isArray(legacyWindow.surfaces)
                ? legacyWindow.surfaces.map(migrateLegacyView)
                : [],
            floatingViews,
            focusedTabGroupId: legacyWindow.focusedPaneId || null,
            focusedFloatingViewId: restoredViewId(
                legacyWindow.focusedFloatingSurfaceId,
            ) || null,
            splitRatio: legacyWindow.splitRatio,
            fullscreenViewId: restoredViewId(
                legacyWindow.fullscreenSurfaceId,
            ) || null,
        },
    };
}

function restoredTabGroup(rawTabGroup, openViewsById, usedViewIds) {
    const requestedIds = Array.isArray(rawTabGroup?.viewIds)
        ? rawTabGroup.viewIds.map(restoredViewId)
        : [];
    const viewIds = requestedIds.filter((viewId) => {
        if (
            typeof viewId !== 'string'
            || !openViewsById[viewId]
            || usedViewIds.has(viewId)
        ) {
            return false;
        }
        usedViewIds.add(viewId);
        return true;
    });
    return {
        viewIds,
        activeViewId: viewIds.includes(restoredViewId(rawTabGroup?.activeViewId))
            ? restoredViewId(rawTabGroup.activeViewId)
            : (viewIds[0] || null),
    };
}

function restoredFloatingViews(
    rawFloatingViews,
    openViewsById,
    usedViewIds,
) {
    if (!Array.isArray(rawFloatingViews)) return {};
    return Object.fromEntries(
        rawFloatingViews.flatMap((rawFloatingView, index) => {
            const viewId = restoredViewId(rawFloatingView?.viewId);
            if (
                typeof viewId !== 'string'
                || !openViewsById[viewId]
                || usedViewIds.has(viewId)
            ) {
                return [];
            }
            usedViewIds.add(viewId);
            const fallbackBounds = {
                ...DEFAULT_FLOATING_VIEW_BOUNDS,
                x: DEFAULT_FLOATING_VIEW_BOUNDS.x + (index * 24),
                y: DEFAULT_FLOATING_VIEW_BOUNDS.y + (index * 24),
            };
            return [[viewId, {
                viewId,
                ...clampFloatingBounds(rawFloatingView, fallbackBounds),
                zIndex: Math.max(
                    1,
                    Number.isFinite(rawFloatingView.zIndex)
                        ? rawFloatingView.zIndex
                        : index + 1,
                ),
            }]];
        }),
    );
}

function restoreLayoutState(rawLayout) {
    if (!isRecord(rawLayout) || !isRecord(rawLayout.tabGroups)) return null;
    const storedViews = Array.isArray(rawLayout.views)
        ? rawLayout.views
        : [];
    const allViewsById = Object.fromEntries(
        storedViews
            .map(restoredView)
            .filter(validDesktopView)
            .map((view) => [view.id, view]),
    );
    const usedViewIds = new Set();
    const tabGroups = {
        [DESKTOP_TAB_GROUP_IDS.LEFT]: restoredTabGroup(
            rawLayout.tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT],
            allViewsById,
            usedViewIds,
        ),
        [DESKTOP_TAB_GROUP_IDS.RIGHT]: restoredTabGroup(
            rawLayout.tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT],
            allViewsById,
            usedViewIds,
        ),
    };
    const floatingByViewId = restoredFloatingViews(
        rawLayout.floatingViews,
        allViewsById,
        usedViewIds,
    );
    const openViewsById = Object.fromEntries(
        [...usedViewIds].map((viewId) => [
            viewId,
            allViewsById[viewId],
        ]),
    );
    const focusedTabGroupId = TAB_GROUP_IDS.includes(
        rawLayout.focusedTabGroupId,
    ) && tabGroups[rawLayout.focusedTabGroupId].activeViewId
        ? rawLayout.focusedTabGroupId
        : (
            tabGroups[DESKTOP_TAB_GROUP_IDS.LEFT].activeViewId
                ? DESKTOP_TAB_GROUP_IDS.LEFT
                : (
                    tabGroups[DESKTOP_TAB_GROUP_IDS.RIGHT].activeViewId
                        ? DESKTOP_TAB_GROUP_IDS.RIGHT
                        : null
                )
        );
    const splitRatio = Number.isFinite(rawLayout.splitRatio)
        ? Math.max(10, Math.min(90, rawLayout.splitRatio))
        : 50;
    const restoredFullscreenViewId = restoredViewId(
        rawLayout.fullscreenViewId,
    );
    const fullscreenViewId = usedViewIds.has(restoredFullscreenViewId)
        ? restoredFullscreenViewId
        : null;
    const restoredFocusedFloatingViewId = restoredViewId(
        rawLayout.focusedFloatingViewId,
    );
    const focusedFloatingViewId = Boolean(
        floatingByViewId[restoredFocusedFloatingViewId],
    )
        ? restoredFocusedFloatingViewId
        : null;
    const floatingZCounter = Math.max(
        0,
        ...Object.values(floatingByViewId)
            .map((floatingView) => floatingView.zIndex),
    );

    return {
        tabGroups,
        openViewsById,
        floatingByViewId,
        focusedTabGroupId,
        focusedFloatingViewId,
        floatingZCounter,
        splitRatio,
        fullscreenViewId,
    };
}

/** Load, migrate, and validate a previously saved Desktop Layout snapshot. */
export function loadDesktopLayoutSnapshot() {
    if (typeof localStorage === 'undefined') return null;
    try {
        const raw = JSON.parse(
            localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY) || 'null',
        );
        if (!isRecord(raw)) return null;
        const snapshot = raw.version === LEGACY_SNAPSHOT_VERSION
            ? migrateLegacySnapshot(raw)
            : (
                [
                    PREVIOUS_SNAPSHOT_VERSION,
                    SNAPSHOT_VERSION,
                ].includes(raw.version)
                    ? {
                        layout: raw.layout,
                    }
                    : null
            );
        if (!snapshot) return null;
        const layoutState = restoreLayoutState(snapshot.layout);
        if (!layoutState) return null;
        return { layoutState };
    } catch {
        return null;
    }
}

/** Build the serializable payload without touching storage. */
export function createDesktopLayoutSnapshot(model) {
    try {
        const placedViewIds = new Set([
            ...TAB_GROUP_IDS.flatMap(
                (tabGroupId) => model.tabGroups[tabGroupId].viewIds,
            ),
            ...(model.floatingViews || []).map(
                (floatingView) => floatingView.viewId,
            ),
        ]);
        const views = [...placedViewIds]
            .map((viewId) => model.openViewsById[viewId])
            .filter(validDesktopView)
            .map(({ iconElement: _iconElement, ...view }) => view);
        return {
            version: SNAPSHOT_VERSION,
            layout: {
                tabGroups: {
                    [DESKTOP_TAB_GROUP_IDS.LEFT]: {
                        viewIds: model.tabGroups[
                            DESKTOP_TAB_GROUP_IDS.LEFT
                        ].viewIds,
                        activeViewId: model.tabGroups[
                            DESKTOP_TAB_GROUP_IDS.LEFT
                        ].activeViewId,
                    },
                    [DESKTOP_TAB_GROUP_IDS.RIGHT]: {
                        viewIds: model.tabGroups[
                            DESKTOP_TAB_GROUP_IDS.RIGHT
                        ].viewIds,
                        activeViewId: model.tabGroups[
                            DESKTOP_TAB_GROUP_IDS.RIGHT
                        ].activeViewId,
                    },
                },
                floatingViews: model.floatingViews || [],
                views,
                focusedTabGroupId: model.focusedTabGroupId,
                focusedFloatingViewId: model.focusedFloatingViewId,
                splitRatio: model.splitRatio,
                fullscreenViewId: model.fullscreenViewId,
            },
        };
    } catch {
        return null;
    }
}

/** Write one already-built payload; storage failures never break the Desktop. */
export function writeDesktopLayoutSnapshot(snapshot) {
    if (!snapshot || typeof localStorage === 'undefined') return;
    try {
        localStorage.setItem(
            DESKTOP_LAYOUT_STORAGE_KEY,
            JSON.stringify(snapshot),
        );
    } catch {
        // Storage may be disabled or full; the in-memory desktop still works.
    }
}

/** Persist serializable layout and navigation—never rendered React content. */
export function saveDesktopLayoutSnapshot(model) {
    writeDesktopLayoutSnapshot(
        createDesktopLayoutSnapshot(model),
    );
}
