import {
    beforeEach,
    describe,
    expect,
    it,
} from 'vitest';

import {
    DESKTOP_LAYOUT_STORAGE_KEY,
    loadDesktopLayoutSnapshot,
} from '../../desktop/desktopLayoutPersistence.js';
import {
    persistFirstRunDesktopLayout,
} from '../setupFirstRunDesktopLayout.js';

const WELCOME = {
    conversation_id: 'welcome-to-omnideck',
    artifact: {
        id: 'welcome-dashboard-id',
        conversation_id: 'welcome-to-omnideck',
        filename: 'welcome_dashboard.html',
        path: '/home/omnideck/welcome_dashboard.html',
        content_type: 'text/html',
        status: 'present',
    },
};

describe('setup first-run Desktop Layout', () => {
    beforeEach(() => {
        localStorage.removeItem(DESKTOP_LAYOUT_STORAGE_KEY);
    });

    it('persists the welcome conversation and dashboard for normal restore', () => {
        expect(persistFirstRunDesktopLayout(WELCOME)).toBe(true);

        const restored = loadDesktopLayoutSnapshot();
        expect(restored.navigationTarget).toEqual({
            kind: 'chat',
            conversationId: 'welcome-to-omnideck',
        });
        expect(restored.layoutState.tabGroups.left).toEqual({
            viewIds: ['destination:conversation'],
            activeViewId: 'destination:conversation',
        });
        expect(restored.layoutState.tabGroups.right).toEqual({
            viewIds: ['artifact:welcome-dashboard-id'],
            activeViewId: 'artifact:welcome-dashboard-id',
        });
    });

    it('does not replace any existing browser layout', () => {
        localStorage.setItem(DESKTOP_LAYOUT_STORAGE_KEY, '{"existing":true}');

        expect(persistFirstRunDesktopLayout(WELCOME)).toBe(false);
        expect(localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY))
            .toBe('{"existing":true}');
    });

    it('does nothing when setup did not return active welcome content', () => {
        expect(persistFirstRunDesktopLayout(null)).toBe(false);
        expect(localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY)).toBeNull();
    });
});
