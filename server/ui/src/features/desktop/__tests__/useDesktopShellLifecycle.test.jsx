import {
    act,
    fireEvent,
    render,
    screen,
    waitFor,
} from '@testing-library/react';
import {
    afterEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest';

import DesktopLayout from '../DesktopLayout.jsx';
import {
    createInitialDesktopLayoutState,
    desktopLayoutReducer,
} from '../desktopLayoutReducer.js';
import {
    DESKTOP_LAYOUT_STORAGE_KEY,
} from '../desktopLayoutPersistence.js';
import { createNavigationView } from '../desktopViews.js';
import useDesktopLayout from '../useDesktopLayout.jsx';
import useDesktopShellLifecycle from '../useDesktopShellLifecycle.js';

const navigation = vi.hoisted(() => ({
    state: {
        navigationTarget: {
            kind: 'chat',
            conversationId: null,
        },
    },
    commands: {
        openTarget: vi.fn(),
    },
}));

vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useDesktopNavigationCommands: () => navigation.commands,
    useDesktopNavigationState: () => navigation.state,
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: () => null,
    useConversationSessionCommands: () => ({
        loadConversation: vi.fn(),
    }),
}));

vi.mock('../../app/AppEffects.jsx', () => ({
    useAppEffectDispatch: () => vi.fn(),
}));

const CHAT = createNavigationView({
    kind: 'chat',
    conversationId: null,
});
const SETTINGS = createNavigationView({
    kind: 'settings',
    tab: null,
});
const INITIAL_LAYOUT = desktopLayoutReducer(
    createInitialDesktopLayoutState(CHAT),
    {
        type: 'OPEN_VIEW',
        view: SETTINGS,
        tabGroupId: 'right',
    },
);
const renderView = (view) => <div>{view.label}</div>;

function LifecycleHarness() {
    const desktopLayout = useDesktopLayout({
        initialLayoutState: INITIAL_LAYOUT,
    });
    useDesktopShellLifecycle({
        desktopLayout,
        desktopRestore: null,
    });
    return (
        <DesktopLayout
            model={desktopLayout.model}
            commands={desktopLayout.commands}
            renderView={renderView}
        />
    );
}

describe('useDesktopShellLifecycle persistence', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        localStorage.removeItem(DESKTOP_LAYOUT_STORAGE_KEY);
    });

    it('writes one snapshot for a complete split drag', async () => {
        const setItem = vi.spyOn(Storage.prototype, 'setItem');
        render(<LifecycleHarness />);

        // Let mount-time navigation reconciliation and its persistence settle,
        // then count only writes caused by the gesture.
        await waitFor(() => expect(setItem).toHaveBeenCalled());
        setItem.mockClear();

        const layout = screen.getByTestId('desktop-layout');
        layout.getBoundingClientRect = () => ({
            left: 0,
            width: 1000,
        });
        const handle = screen.getByRole(
            'separator',
            { name: 'Resize tab groups' },
        );

        act(() => {
            fireEvent.mouseDown(handle, { clientX: 500 });
            fireEvent.mouseMove(document, { clientX: 560 });
            fireEvent.mouseMove(document, { clientX: 620 });
            fireEvent.mouseMove(document, { clientX: 680 });
            fireEvent.mouseUp(document);
        });

        await waitFor(() => expect(setItem).toHaveBeenCalledTimes(1));
        expect(JSON.parse(
            localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY),
        ).layout.splitRatio).toBe(68);
    });
});
