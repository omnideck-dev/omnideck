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
import {
    createNavigationView,
} from '../../navigation/desktopNavigationViews.js';
import useDesktopLayout from '../useDesktopLayout.jsx';
import useDesktopShellLifecycle from '../useDesktopShellLifecycle.js';

const sessionHarness = vi.hoisted(() => ({
    activeConversationId: 'fresh-conversation',
    savedConversationId: null,
    loadConversation: vi.fn(),
}));
const appEffectHarness = vi.hoisted(() => ({
    dispatch: vi.fn(),
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: () => sessionHarness.activeConversationId,
    useSavedConversationId: () => sessionHarness.savedConversationId,
    useConversationSessionCommands: () => ({
        loadConversation: sessionHarness.loadConversation,
    }),
}));

vi.mock('../../app/AppEffects.jsx', () => ({
    useAppEffectDispatch: () => appEffectHarness.dispatch,
}));

const CHAT = createNavigationView({
    kind: 'chat',
    conversationId: null,
});
const SETTINGS = createNavigationView({
    kind: 'settings',
    tab: null,
});
const AGENTS = createNavigationView({
    kind: 'agents',
    profileId: null,
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

function LifecycleHarness({
    initialLayoutState = INITIAL_LAYOUT,
    desktopRestore = null,
}) {
    const desktopLayout = useDesktopLayout({
        initialLayoutState,
    });
    useDesktopShellLifecycle({
        desktopLayout,
        desktopRestore,
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
        sessionHarness.activeConversationId = 'fresh-conversation';
        sessionHarness.savedConversationId = null;
        sessionHarness.loadConversation.mockReset();
        appEffectHarness.dispatch.mockReset();
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

    it('persists a fresh chat without its live ID, then records the server-confirmed ID', async () => {
        const liveChat = createNavigationView({
            kind: 'chat',
            conversationId: 'fresh-conversation',
        });
        const layout = createInitialDesktopLayoutState(liveChat);
        const { rerender } = render(<LifecycleHarness initialLayoutState={layout} />);
        const savedId = () => JSON.parse(
            localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY),
        ).layout.views[0].identity.navigationTarget.conversationId;
        await waitFor(() => expect(savedId()).toBeNull());

        sessionHarness.savedConversationId = 'fresh-conversation';
        rerender(<LifecycleHarness initialLayoutState={layout} />);
        await waitFor(() => expect(savedId()).toBe('fresh-conversation'));
    });

    it('restores a fresh chat locally without loading or closing a conversation', async () => {
        render(<LifecycleHarness desktopRestore={{ layoutState: INITIAL_LAYOUT }} />);
        await waitFor(() => expect(localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY)).not.toBeNull());
        expect(sessionHarness.loadConversation).not.toHaveBeenCalled();
        expect(appEffectHarness.dispatch).not.toHaveBeenCalled();
        expect(screen.getByTestId('desktop-view-destination:settings'))
            .toHaveAttribute('data-visible', 'true');
    });

    it('replaces an unloadable Conversation without stealing restored focus', async () => {
        sessionHarness.loadConversation.mockRejectedValue(new Error('not found'));
        const staleConversation = createNavigationView({
            kind: 'chat',
            conversationId: 'missing-conversation',
        });
        const restoredLayout = desktopLayoutReducer(
            createInitialDesktopLayoutState(staleConversation),
            {
                type: 'OPEN_VIEW',
                view: AGENTS,
                tabGroupId: 'left',
            },
        );
        const desktopRestore = { layoutState: restoredLayout };

        render(
            <LifecycleHarness
                initialLayoutState={restoredLayout}
                desktopRestore={desktopRestore}
            />,
        );

        await waitFor(() => {
            expect(sessionHarness.loadConversation)
                .toHaveBeenCalledWith('missing-conversation');
        });
        await waitFor(() => {
            expect(
                screen.getByTestId('desktop-view-destination:agents'),
            ).toHaveAttribute('data-visible', 'true');
        });

        // The stale domain identity is still repaired and persisted even
        // though the active Agents location is preserved.
        await waitFor(() => {
            const saved = JSON.parse(
                localStorage.getItem(DESKTOP_LAYOUT_STORAGE_KEY),
            );
            const conversationView = saved.layout.views.find(
                (view) => view.id === staleConversation.id,
            );
            expect(
                conversationView.identity.navigationTarget.conversationId,
            )
                .toBeNull();
        });
    });
});
