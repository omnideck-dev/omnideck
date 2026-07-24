import {
    DEFAULT_FLOATING_WINDOW_BOUNDS,
    DESKTOP_PANE_IDS,
} from './desktopWindowReducer.js';

export const DESKTOP_WINDOW_STORAGE_KEY = 'omnideck_desktop_window_v1';
const SNAPSHOT_VERSION = 1;
const PANE_IDS = Object.values(DESKTOP_PANE_IDS);
const SURFACE_KINDS = new Set([
    'conversation',
    'conversation-execution',
    'artifact-file',
    'custom-app',
    'settings',
    'agents',
    'routines',
    'artifacts',
    'apps',
]);

function isRecord(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function validSurface(surface) {
    if (
        !isRecord(surface)
        || typeof surface.id !== 'string'
        || typeof surface.kind !== 'string'
        || typeof surface.label !== 'string'
        || !SURFACE_KINDS.has(surface.kind)
    ) {
        return false;
    }
    if (surface.kind === 'custom-app') {
        return isRecord(surface.app) && typeof surface.app.slug === 'string';
    }
    if (surface.kind === 'artifact-file') {
        return isRecord(surface.artifact);
    }
    if (surface.kind === 'conversation-execution') {
        return typeof surface.conversationId === 'string'
            && typeof surface.agentId === 'string'
            && ['browser', 'terminal'].includes(surface.resourceId);
    }
    if (surface.kind === 'conversation') {
        return isRecord(surface.destination)
            && ['chat', 'network'].includes(surface.destination.kind);
    }
    return true;
}

function restoredPane(rawPane, surfacesById, usedSurfaceIds) {
    const requestedIds = Array.isArray(rawPane?.surfaceIds)
        ? rawPane.surfaceIds
        : [];
    const surfaceIds = requestedIds.filter((surfaceId) => {
        if (
            typeof surfaceId !== 'string'
            || !surfacesById[surfaceId]
            || usedSurfaceIds.has(surfaceId)
        ) {
            return false;
        }
        usedSurfaceIds.add(surfaceId);
        return true;
    });
    return {
        surfaceIds,
        activeSurfaceId: surfaceIds.includes(rawPane?.activeSurfaceId)
            ? rawPane.activeSurfaceId
            : (surfaceIds[0] || null),
    };
}

function restoredFloatingWindows(
    rawWindows,
    surfacesById,
    usedSurfaceIds,
) {
    if (!Array.isArray(rawWindows)) return {};
    return Object.fromEntries(rawWindows.flatMap((rawWindow, index) => {
        const surfaceId = rawWindow?.surfaceId;
        if (
            typeof surfaceId !== 'string'
            || !surfacesById[surfaceId]
            || usedSurfaceIds.has(surfaceId)
        ) {
            return [];
        }
        usedSurfaceIds.add(surfaceId);
        const numberOr = (value, fallback) => (
            Number.isFinite(value) ? value : fallback
        );
        return [[surfaceId, {
            surfaceId,
            x: Math.max(0, numberOr(
                rawWindow.x,
                DEFAULT_FLOATING_WINDOW_BOUNDS.x + (index * 24),
            )),
            y: Math.max(0, numberOr(
                rawWindow.y,
                DEFAULT_FLOATING_WINDOW_BOUNDS.y + (index * 24),
            )),
            width: Math.max(320, numberOr(
                rawWindow.width,
                DEFAULT_FLOATING_WINDOW_BOUNDS.width,
            )),
            height: Math.max(220, numberOr(
                rawWindow.height,
                DEFAULT_FLOATING_WINDOW_BOUNDS.height,
            )),
            zIndex: Math.max(1, numberOr(rawWindow.zIndex, index + 1)),
        }]];
    }));
}

function restoreWindowState(rawWindow) {
    if (!isRecord(rawWindow) || !isRecord(rawWindow.panes)) return null;
    const storedSurfaces = Array.isArray(rawWindow.surfaces)
        ? rawWindow.surfaces
        : [];
    const surfacesById = Object.fromEntries(
        storedSurfaces
            .filter(validSurface)
            .map((surface) => [surface.id, surface]),
    );
    const usedSurfaceIds = new Set();
    const panes = {
        [DESKTOP_PANE_IDS.LEFT]: restoredPane(
            rawWindow.panes[DESKTOP_PANE_IDS.LEFT],
            surfacesById,
            usedSurfaceIds,
        ),
        [DESKTOP_PANE_IDS.RIGHT]: restoredPane(
            rawWindow.panes[DESKTOP_PANE_IDS.RIGHT],
            surfacesById,
            usedSurfaceIds,
        ),
    };
    const floatingWindowsBySurfaceId = restoredFloatingWindows(
        rawWindow.floatingWindows,
        surfacesById,
        usedSurfaceIds,
    );
    const placedSurfacesById = Object.fromEntries(
        [...usedSurfaceIds].map((surfaceId) => [
            surfaceId,
            surfacesById[surfaceId],
        ]),
    );
    const focusedPaneId = PANE_IDS.includes(rawWindow.focusedPaneId)
        && panes[rawWindow.focusedPaneId].activeSurfaceId
        ? rawWindow.focusedPaneId
        : (
            panes[DESKTOP_PANE_IDS.LEFT].activeSurfaceId
                ? DESKTOP_PANE_IDS.LEFT
                : (
                    panes[DESKTOP_PANE_IDS.RIGHT].activeSurfaceId
                        ? DESKTOP_PANE_IDS.RIGHT
                        : null
                )
        );
    const splitRatio = Number.isFinite(rawWindow.splitRatio)
        ? Math.max(10, Math.min(90, rawWindow.splitRatio))
        : 50;
    const fullscreenSurfaceId = usedSurfaceIds.has(rawWindow.fullscreenSurfaceId)
        ? rawWindow.fullscreenSurfaceId
        : null;
    const focusedFloatingSurfaceId = Boolean(
        floatingWindowsBySurfaceId[rawWindow.focusedFloatingSurfaceId],
    )
        ? rawWindow.focusedFloatingSurfaceId
        : null;
    const floatingZCounter = Math.max(
        0,
        ...Object.values(floatingWindowsBySurfaceId)
            .map((floatingWindow) => floatingWindow.zIndex),
    );

    return {
        panes,
        surfacesById: placedSurfacesById,
        floatingWindowsBySurfaceId,
        focusedPaneId,
        focusedFloatingSurfaceId,
        floatingZCounter,
        splitRatio,
        fullscreenSurfaceId,
        pendingFocus: null,
    };
}

/** Load and validate a previously saved desktop layout. */
export function loadDesktopWindowSnapshot() {
    if (typeof localStorage === 'undefined') return null;
    try {
        const raw = JSON.parse(
            localStorage.getItem(DESKTOP_WINDOW_STORAGE_KEY) || 'null',
        );
        if (!isRecord(raw) || raw.version !== SNAPSHOT_VERSION) return null;
        const windowState = restoreWindowState(raw.window);
        if (!windowState) return null;
        return {
            windowState,
            navigationDestination: isRecord(raw.navigationDestination)
                && typeof raw.navigationDestination.kind === 'string'
                ? raw.navigationDestination
                : null,
        };
    } catch {
        return null;
    }
}

/** Persist serializable placement and navigation—never rendered feature data. */
export function saveDesktopWindowSnapshot(model, navigationDestination) {
    if (typeof localStorage === 'undefined') return;
    try {
        const placedSurfaceIds = new Set(
            [
                ...PANE_IDS.flatMap(
                    (paneId) => model.panes[paneId].surfaceIds,
                ),
                ...(model.floatingWindows || []).map(
                    (floatingWindow) => floatingWindow.surfaceId,
                ),
            ],
        );
        const surfaces = [...placedSurfaceIds]
            .map((surfaceId) => model.surfacesById[surfaceId])
            .filter(validSurface)
            .map(({ iconElement: _iconElement, ...surface }) => surface);
        localStorage.setItem(DESKTOP_WINDOW_STORAGE_KEY, JSON.stringify({
            version: SNAPSHOT_VERSION,
            window: {
                panes: {
                    [DESKTOP_PANE_IDS.LEFT]: {
                        surfaceIds: model.panes[DESKTOP_PANE_IDS.LEFT].surfaceIds,
                        activeSurfaceId: model.panes[DESKTOP_PANE_IDS.LEFT].activeSurfaceId,
                    },
                    [DESKTOP_PANE_IDS.RIGHT]: {
                        surfaceIds: model.panes[DESKTOP_PANE_IDS.RIGHT].surfaceIds,
                        activeSurfaceId: model.panes[DESKTOP_PANE_IDS.RIGHT].activeSurfaceId,
                    },
                },
                floatingWindows: model.floatingWindows || [],
                surfaces,
                focusedPaneId: model.focusedPaneId,
                focusedFloatingSurfaceId: model.focusedFloatingSurfaceId,
                splitRatio: model.splitRatio,
                fullscreenSurfaceId: model.fullscreenSurfaceId,
            },
            navigationDestination,
        }));
    } catch {
        // Storage may be disabled or full; the in-memory desktop still works.
    }
}
