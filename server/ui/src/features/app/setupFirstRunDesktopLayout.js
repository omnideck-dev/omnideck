import {
    DESKTOP_LAYOUT_STORAGE_KEY,
    saveDesktopLayoutSnapshot,
} from '../desktop/desktopLayoutPersistence.js';
import { DESKTOP_TAB_GROUP_IDS } from '../desktop/desktopLayoutReducer.js';
import {
    createArtifactView,
    createNavigationView,
} from '../desktop/desktopViews.js';

/**
 * Persist the one-time layout shown immediately after setup.
 *
 * SetupGate calls this before Desktop mounts, which lets the ordinary restore
 * path load the seeded conversation and place its welcome dashboard. This is
 * deliberately a real persisted snapshot, not a second startup-only layout
 * mechanism.
 */
export function persistFirstRunDesktopLayout(welcome) {
    if (
        typeof localStorage === 'undefined'
        || !welcome?.conversation_id
        || !welcome?.artifact
    ) {
        return false;
    }

    try {
        // Setup normally finishes before Desktop has ever mounted. Still,
        // never replace a snapshot if the browser already has one.
        if (localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY) !== null) {
            return false;
        }

        const navigationTarget = {
            kind: 'chat',
            conversationId: welcome.conversation_id,
        };
        const conversationView = createNavigationView(navigationTarget);
        const dashboardView = createArtifactView(welcome.artifact);
        if (!conversationView || !dashboardView) return false;

        const model = {
            tabGroups: {
                [DESKTOP_TAB_GROUP_IDS.LEFT]: {
                    viewIds: [conversationView.id],
                    activeViewId: conversationView.id,
                },
                [DESKTOP_TAB_GROUP_IDS.RIGHT]: {
                    viewIds: [dashboardView.id],
                    activeViewId: dashboardView.id,
                },
            },
            openViewsById: {
                [conversationView.id]: conversationView,
                [dashboardView.id]: dashboardView,
            },
            floatingViews: [],
            focusedTabGroupId: DESKTOP_TAB_GROUP_IDS.LEFT,
            focusedFloatingViewId: null,
            splitRatio: 50,
            fullscreenViewId: null,
        };

        saveDesktopLayoutSnapshot(model);
        return localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY) !== null;
    } catch {
        // Storage can be disabled. Optional onboarding placement must never
        // prevent the setup wizard from completing.
        return false;
    }
}
