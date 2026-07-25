import { cleanup, render as _render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from '../Sidebar.jsx';
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
        openSettings: vi.fn(),
    },
    customApps: {
        enabled: false,
    },
}));

vi.mock('../../features/navigation/DesktopNavigation.jsx', () => ({
    useCurrentNavigationTarget: () => navigationHarness.navigationTarget,
    useDesktopNavigationCommands: () => navigationHarness.commands,
}));

vi.mock('../../features/customApps/CustomApps.jsx', () => ({
    useCustomApps: () => navigationHarness.customApps,
}));

// The expanded sidebar renders ConversationsPanel (conversations context) and
// reads the theme context for its toggle — so every render supplies both.
const Wrapper = ({ children }) => (
    <AppEffectsProvider>
        <ThemeProvider>
            <ConversationCatalogProvider>{children}</ConversationCatalogProvider>
        </ThemeProvider>
    </AppEffectsProvider>
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

    it('shows the Apps navigationTarget only when Custom Apps are enabled', async () => {
        const user = userEvent.setup();
        const hidden = setup();
        expect(screen.queryByTestId('sidebar-nav-apps')).not.toBeInTheDocument();
        expect(hidden.navigation.openApps).not.toHaveBeenCalled();

        cleanup();
        navigationHarness.customApps.enabled = true;
        const { navigation } = setup();
        expect(screen.getByText('Custom Apps')).toBeInTheDocument();
        await user.click(screen.getByTestId('sidebar-nav-apps'));
        expect(navigation.openApps).toHaveBeenCalledOnce();
    });

    it('does not expose a special Home navigationTarget for Custom Apps', () => {
        navigationHarness.customApps.enabled = true;
        setup();

        expect(screen.queryByTestId('sidebar-nav-home')).not.toBeInTheDocument();
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
