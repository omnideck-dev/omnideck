import {
    cleanup,
    fireEvent,
    render as _render,
    screen,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from '../Sidebar.jsx';
import { ToastProvider } from '../ToastProvider.jsx';
import { ConversationCatalogProvider } from '../../features/conversation/catalog/ConversationCatalog.jsx';
import { AppEffectsProvider } from '../../features/app/AppEffects.jsx';
import { ThemeProvider } from '../../contexts/Theme.jsx';

const navigationHarness = vi.hoisted(() => ({
    navigationTarget: { kind: 'chat', conversationId: 'conversation-1' },
    commands: {
        openChat: vi.fn(),
        openAgents: vi.fn(),
        openRoutines: vi.fn(),
        openArtifacts: vi.fn(),
        openApps: vi.fn(),
        openCustomApp: vi.fn(),
        openSettings: vi.fn(),
    },
    customApps: {
        enabled: false,
        catalog: {
            apps: [],
            loaded: true,
            loading: false,
        },
        pinnedAppSlugs: [],
        pinApp: vi.fn(),
        unpinApp: vi.fn(),
        reorderPinnedApps: vi.fn(),
    },
}));

vi.mock('../../features/navigation/DesktopNavigation.jsx', () => ({
    useCurrentNavigationTarget: () => navigationHarness.navigationTarget,
    useDesktopNavigationCommands: () => navigationHarness.commands,
}));

vi.mock('../../features/customApps/CustomApps.jsx', () => ({
    useCustomApps: () => navigationHarness.customApps,
}));

// The expanded sidebar renders ConversationsPanel (conversation + toast
// contexts) and reads the theme context for its toggle.
const Wrapper = ({ children }) => (
    <ToastProvider>
        <AppEffectsProvider>
            <ThemeProvider>
                <ConversationCatalogProvider>{children}</ConversationCatalogProvider>
            </ThemeProvider>
        </AppEffectsProvider>
    </ToastProvider>
);
const render = (ui, options) => _render(ui, { wrapper: Wrapper, ...options });

const COLLAPSE_KEY = 'computron_sidebar_collapsed';

function setup(props = {}) {
    const onNewConversation = vi.fn();
    render(
        <Sidebar
            onNewConversation={onNewConversation}
            {...props}
        />,
    );
    return { navigation: navigationHarness.commands, onNewConversation };
}

beforeEach(() => {
    localStorage.clear();
    navigationHarness.navigationTarget = { kind: 'chat', conversationId: 'conversation-1' };
    navigationHarness.customApps.enabled = false;
    navigationHarness.customApps.catalog.apps = [];
    navigationHarness.customApps.pinnedAppSlugs = [];
    navigationHarness.customApps.pinApp.mockReset();
    navigationHarness.customApps.unpinApp.mockReset();
    navigationHarness.customApps.reorderPinnedApps.mockReset();
    Object.values(navigationHarness.commands).forEach((command) => command.mockReset());
});
afterEach(() => localStorage.clear());

describe('Sidebar', () => {
    it('starts expanded with the wordmark and nav labels visible', () => {
        setup();
        expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'false');
        expect(screen.getByText('OMNIDECK')).toBeInTheDocument();
        expect(screen.getByText('New chat')).toBeInTheDocument();
        expect(screen.getByText('Routines')).toBeInTheDocument();
    });

    it('collapses on toggle and hides labels', async () => {
        const user = userEvent.setup();
        setup();
        await user.click(screen.getByTestId('sidebar-toggle'));
        expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true');
        expect(screen.queryByText('OMNIDECK')).not.toBeInTheDocument();
        expect(screen.queryByText('New chat')).not.toBeInTheDocument();
        expect(screen.queryByText('Routines')).not.toBeInTheDocument();
    });

    it('keeps collapsed New chat above the flexible footer spacer', async () => {
        const user = userEvent.setup();
        setup();
        await user.click(screen.getByTestId('sidebar-toggle'));

        const newChat = screen.getByTestId('sidebar-new-chat');
        const spacer = screen.getByTestId('sidebar-collapsed-spacer');
        const settings = screen.getByTestId('sidebar-settings');
        expect(newChat.compareDocumentPosition(spacer)
            & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(spacer.compareDocumentPosition(settings)
            & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    });

    it('persists the collapsed state to localStorage', async () => {
        const user = userEvent.setup();
        setup();
        await user.click(screen.getByTestId('sidebar-toggle'));
        expect(localStorage.getItem(COLLAPSE_KEY)).toBe('1');
        await user.click(screen.getByTestId('sidebar-toggle'));
        expect(localStorage.getItem(COLLAPSE_KEY)).toBe('0');
    });

    it('reads the initial collapsed state from localStorage', () => {
        localStorage.setItem(COLLAPSE_KEY, '1');
        setup();
        expect(screen.getByTestId('sidebar')).toHaveAttribute('data-collapsed', 'true');
    });

    it('fires onNewConversation from the New chat button', async () => {
        const user = userEvent.setup();
        const { onNewConversation } = setup();
        await user.click(screen.getByTestId('sidebar-new-chat'));
        expect(onNewConversation).toHaveBeenCalledOnce();
    });

    it('toggles the theme from the theme button', async () => {
        const user = userEvent.setup();
        setup();
        const btn = screen.getByTestId('sidebar-theme-toggle');
        // jsdom has no matchMedia, so the provider starts on its light default.
        expect(btn).toHaveAttribute('title', 'Switch to dark theme');
        await user.click(btn);
        expect(btn).toHaveAttribute('title', 'Switch to light theme');
        expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });

    it('opens a navigationTarget from a navigation item', async () => {
        const user = userEvent.setup();
        const { navigation } = setup();
        await user.click(screen.getByTestId('sidebar-nav-routines'));
        expect(navigation.openRoutines).toHaveBeenCalledOnce();
    });

    it('returns to chat from an already-active navigation item', async () => {
        const user = userEvent.setup();
        navigationHarness.navigationTarget = { kind: 'routines', routineId: null, runId: null };
        const { navigation } = setup();
        expect(screen.getByTestId('sidebar-nav-routines').className)
            .toContain('active');
        await user.click(screen.getByTestId('sidebar-nav-routines'));
        expect(navigation.openChat).toHaveBeenCalledOnce();
    });

    it('opens the Agents navigationTarget from its navigation item', async () => {
        const user = userEvent.setup();
        const { navigation } = setup();
        expect(screen.getByText('Agents')).toBeInTheDocument();
        await user.click(screen.getByTestId('sidebar-nav-agents'));
        expect(navigation.openAgents).toHaveBeenCalledOnce();
    });

    it('shows the Apps navigationTarget only when Apps are enabled', async () => {
        const user = userEvent.setup();
        const hidden = setup();
        expect(screen.queryByTestId('sidebar-nav-apps')).not.toBeInTheDocument();
        expect(hidden.navigation.openApps).not.toHaveBeenCalled();

        cleanup();
        navigationHarness.customApps.enabled = true;
        const { navigation } = setup();
        expect(screen.getByTestId('sidebar-nav-apps')).toHaveTextContent('Apps');
        await user.click(screen.getByTestId('sidebar-nav-apps'));
        expect(navigation.openApps).toHaveBeenCalledOnce();
    });

    it('does not expose a special Home navigationTarget for Apps', () => {
        navigationHarness.customApps.enabled = true;
        setup();

        expect(screen.queryByTestId('sidebar-nav-home')).not.toBeInTheDocument();
    });

    it('stacks destinations, pinned Apps, and conversation controls in order', () => {
        navigationHarness.customApps.enabled = true;
        navigationHarness.customApps.catalog.apps = [
            { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' },
        ];
        navigationHarness.customApps.pinnedAppSlugs = ['text-lab'];
        setup();

        const destination = screen.getByTestId('sidebar-nav-apps');
        const pinned = screen.getByTestId('sidebar-pinned-section');
        const conversations = screen.getByTestId('recent-conversations');
        expect(pinned).toHaveTextContent('Apps');
        expect(destination.compareDocumentPosition(pinned)
            & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(pinned.compareDocumentPosition(conversations)
            & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(conversations).toContainElement(screen.getByTestId('sidebar-new-chat'));
        expect(conversations).toContainElement(screen.getByTestId('recent-search'));
    });

    it('omits the Apps section when no Apps are pinned', () => {
        navigationHarness.customApps.enabled = true;
        navigationHarness.customApps.catalog.apps = [
            { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' },
        ];
        setup();

        expect(screen.queryByTestId('sidebar-pinned-section')).not.toBeInTheDocument();
        expect(screen.getByTestId('sidebar-nav-apps')).toBeInTheDocument();
    });

    it('pins and opens Apps from the Apps section', async () => {
        const user = userEvent.setup();
        navigationHarness.customApps.enabled = true;
        navigationHarness.customApps.catalog.apps = [
            { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' },
            { slug: 'notes-lab', title: 'Notes Lab', icon: 'bi-journal' },
        ];
        navigationHarness.customApps.pinnedAppSlugs = ['text-lab'];
        const { navigation } = setup();

        await user.click(screen.getByTestId('sidebar-pinned-add'));
        expect(screen.getByTestId('sidebar-pinned-picker')).toBeInTheDocument();
        expect(screen.queryByTestId('sidebar-pin-option-text-lab')).not.toBeInTheDocument();
        await user.click(screen.getByTestId('sidebar-pin-option-notes-lab'));
        expect(navigationHarness.customApps.pinApp).toHaveBeenCalledWith('notes-lab');

        await user.click(screen.getByTestId('sidebar-pinned-app-text-lab'));
        expect(navigation.openCustomApp).toHaveBeenCalledWith('text-lab');
    });

    it('persists destination order and supports Alt+Arrow reordering', () => {
        localStorage.setItem(
            'omnideck_sidebar_navigation_order',
            JSON.stringify(['routines', 'agents', 'artifacts', 'apps']),
        );
        setup();
        const nav = screen.getByRole('navigation');
        expect([...nav.querySelectorAll('[data-reorder-id]')]
            .map((row) => row.dataset.reorderId))
            .toEqual(['routines', 'agents', 'artifacts']);

        const agents = screen.getByTestId('sidebar-nav-agents');
        expect(agents).toHaveAttribute(
            'aria-keyshortcuts',
            'Alt+ArrowUp Alt+ArrowDown',
        );
        fireEvent.keyDown(agents, { key: 'ArrowDown', altKey: true });
        expect([...nav.querySelectorAll('[data-reorder-id]')]
            .map((row) => row.dataset.reorderId))
            .toEqual(['routines', 'artifacts', 'agents']);
        expect(JSON.parse(localStorage.getItem('omnideck_sidebar_navigation_order')))
            .toEqual(['routines', 'artifacts', 'agents', 'apps']);
        expect(screen.getByRole('status')).toHaveTextContent(
            'Agents moved to position 3 of 3',
        );
    });

    it('moves destinations from their right-click menu', async () => {
        const user = userEvent.setup();
        setup();
        fireEvent.contextMenu(screen.getByTestId('sidebar-nav-routines'), {
            clientX: 20,
            clientY: 30,
        });

        expect(screen.getByTestId('sidebar-reorder-menu')).toBeInTheDocument();
        await user.click(screen.getByTestId('sidebar-reorder-move-up'));
        const nav = screen.getByRole('navigation');
        expect([...nav.querySelectorAll('[data-reorder-id]')]
            .map((row) => row.dataset.reorderId))
            .toEqual(['routines', 'agents', 'artifacts']);
    });

    it('reorders and unpins sidebar Apps with keyboard and context actions', async () => {
        const user = userEvent.setup();
        navigationHarness.customApps.enabled = true;
        navigationHarness.customApps.catalog.apps = [
            { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' },
            { slug: 'notes-lab', title: 'Notes Lab', icon: 'bi-journal' },
        ];
        navigationHarness.customApps.pinnedAppSlugs = ['text-lab', 'notes-lab'];
        setup();

        const notes = screen.getByTestId('sidebar-pinned-app-notes-lab');
        fireEvent.keyDown(notes, { key: 'ArrowUp', altKey: true });
        expect(navigationHarness.customApps.reorderPinnedApps)
            .toHaveBeenCalledWith(['notes-lab', 'text-lab']);

        fireEvent.contextMenu(screen.getByTestId('sidebar-pinned-app-text-lab'), {
            clientX: 20,
            clientY: 30,
        });
        await user.click(screen.getByTestId('sidebar-reorder-unpin'));
        expect(navigationHarness.customApps.unpinApp).toHaveBeenCalledWith('text-lab');
    });

    it('opens settings from the footer', async () => {
        const user = userEvent.setup();
        const { navigation } = setup();
        await user.click(screen.getByTestId('sidebar-settings'));
        expect(navigation.openSettings).toHaveBeenCalledOnce();
    });

it('hides the desktop button unless desktop is enabled', () => {
        setup();
        expect(screen.queryByTestId('sidebar-desktop')).not.toBeInTheDocument();
    });

    it('shows the desktop button and fires onOpenDesktop when enabled', async () => {
        const user = userEvent.setup();
        const onOpenDesktop = vi.fn();
        setup({ desktopEnabled: true, onOpenDesktop });
        await user.click(screen.getByTestId('sidebar-desktop'));
        expect(onOpenDesktop).toHaveBeenCalledOnce();
    });
});
