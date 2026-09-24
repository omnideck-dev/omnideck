import { describe, expect, it } from 'vitest';

import {
    createCustomAppView,
    customAppViewId,
} from '../customAppDesktopViews.js';

describe('Custom App desktop View descriptions', () => {
    it('owns its slug-based identity and pin and reload actions', () => {
        const app = {
            slug: 'text-lab',
            title: 'Text Lab',
            icon: 'bi-fonts',
        };

        expect(customAppViewId(app.slug)).toBe('custom-app:text-lab');
        expect(createCustomAppView(app, 3)).toMatchObject({
            id: 'custom-app:text-lab',
            type: 'custom-app',
            identity: {
                appSlug: 'text-lab',
                navigationTarget: {
                    kind: 'custom-app',
                    appSlug: 'text-lab',
                },
            },
            app,
            reloadSignal: 3,
            pinnedToSidebar: false,
            actions: [
                {
                    id: 'toggle-sidebar-pin',
                    label: 'Pin to sidebar',
                    ariaLabel: 'Pin Text Lab to sidebar',
                    icon: 'bi-pin-angle',
                    testid: 'pin-view-custom-app:text-lab',
                },
                {
                    id: 'reload',
                    label: 'Reload',
                    ariaLabel: 'Reload Text Lab',
                    icon: 'bi-arrow-clockwise',
                    testid: 'reload-view-custom-app:text-lab',
                },
            ],
        });

        expect(createCustomAppView(app, 3, true).actions[0]).toMatchObject({
            id: 'toggle-sidebar-pin',
            label: 'Unpin from sidebar',
            ariaLabel: 'Unpin Text Lab from sidebar',
            icon: 'bi-pin-angle-fill',
        });
    });
});
