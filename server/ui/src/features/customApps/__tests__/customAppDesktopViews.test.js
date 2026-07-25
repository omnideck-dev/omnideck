import { describe, expect, it } from 'vitest';

import {
    createCustomAppView,
    customAppViewId,
} from '../customAppDesktopViews.js';

describe('Custom App desktop View descriptions', () => {
    it('owns its slug-based identity and runtime reload action', () => {
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
            actions: ['reload'],
        });
    });
});
