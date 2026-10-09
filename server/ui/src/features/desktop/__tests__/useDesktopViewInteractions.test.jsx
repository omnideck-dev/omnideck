import { renderHook } from '@testing-library/react';
import {
    afterEach, describe, expect, it, vi,
} from 'vitest';

import { AppEffectsProvider } from '../../app/AppEffects.jsx';

vi.mock('../../../hooks/useIsMobileViewport.js', () => ({
    default: vi.fn(() => false),
}));

const { default: useDesktopViewInteractions } = await import(
    '../useDesktopViewInteractions.js'
);
const { default: useIsMobileViewport } = await import(
    '../../../hooks/useIsMobileViewport.js'
);

const VIEW = { id: 'destination:conversation', label: 'Chat', closable: true };

function desktopLayout() {
    return {
        model: {
            openViewsById: { [VIEW.id]: VIEW },
            tabGroups: {
                left: { viewIds: [VIEW.id], activeViewId: VIEW.id, views: [VIEW] },
                right: { viewIds: [], activeViewId: null, views: [] },
            },
        },
        commands: {
            selectView: vi.fn(),
            closeViews: vi.fn(),
            moveView: vi.fn(),
            floatView: vi.fn(),
            enterFullscreen: vi.fn(),
        },
    };
}

const wrapper = ({ children }) => (
    <AppEffectsProvider>{children}</AppEffectsProvider>
);

afterEach(() => {
    useIsMobileViewport.mockReturnValue(false);
});

describe('useDesktopViewInteractions', () => {
    it('omits the move action from getViewActions on mobile', () => {
        useIsMobileViewport.mockReturnValue(true);
        const { result } = renderHook(
            () => useDesktopViewInteractions({ desktopLayout: desktopLayout() }),
            { wrapper },
        );

        const actions = result.current.getViewActions(VIEW, 'left');
        expect(actions.find((action) => action.id === 'move')).toBeUndefined();
    });

    it('keeps the move action from getViewActions on desktop', () => {
        useIsMobileViewport.mockReturnValue(false);
        const { result } = renderHook(
            () => useDesktopViewInteractions({ desktopLayout: desktopLayout() }),
            { wrapper },
        );

        const actions = result.current.getViewActions(VIEW, 'left');
        expect(actions.find((action) => action.id === 'move')).toBeDefined();
    });
});
