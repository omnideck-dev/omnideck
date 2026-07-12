import { fireEvent, render as _render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import RecentConversations from '../RecentConversations.jsx';
import { ConversationsProvider } from '../../contexts/Conversations.jsx';

// RecentConversations now reads its list from the conversations context, so
// every render goes through the provider (which fetches the list on mount).
const render = (ui, options) => _render(ui, { wrapper: ConversationsProvider, ...options });

// A fixed mid-day instant. Both the session timestamps and the component's
// own `new Date()` are pinned to this, so the day-bucket assignments don't
// shift with the wall clock (notably the midnight boundary, where a session
// dated "1 hour ago" would otherwise fall into yesterday's bucket).
const FIXED_NOW = new Date('2026-06-01T12:00:00.000Z');

function isoAgo({ days = 0, hours = 0 }) {
    const d = new Date(FIXED_NOW);
    d.setDate(d.getDate() - days);
    d.setHours(d.getHours() - hours);
    return d.toISOString();
}

// A spread of conversations across the day buckets.
const SESSIONS = [
    { conversation_id: 'c1', title: 'muxer flush bug', started_at: isoAgo({ hours: 1 }) },
    { conversation_id: 'c2', title: 'snake game', started_at: isoAgo({ hours: 3 }) },
    { conversation_id: 'c3', title: 'release notes draft', started_at: isoAgo({ days: 1 }) },
    { conversation_id: 'c4', title: 'eval pass', started_at: isoAgo({ days: 6 }) },
];

function mockFetch(sessions = SESSIONS) {
    global.fetch = vi.fn((url, opts) => {
        const method = opts?.method;
        if (method === 'DELETE' || method === 'PATCH') {
            return Promise.resolve({ ok: true, status: 204 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(sessions) });
    });
}

/** Open a row's 3-dot menu and return the menu element. */
async function openRowMenu(user, row) {
    await user.click(within(row).getByTestId('recent-menu-trigger'));
    return screen.getByTestId('recent-menu');
}

beforeEach(() => {
    // Fake only Date (not setTimeout/microtasks) so waitFor + userEvent still
    // run on real timers while the component reads the pinned "now".
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
    mockFetch();
});
afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe('RecentConversations', () => {
    it('lists fetched conversations grouped by day', async () => {
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));
        expect(screen.getByText('Today')).toBeInTheDocument();
        expect(screen.getByText('Yesterday')).toBeInTheDocument();
        expect(screen.getByText('Earlier')).toBeInTheDocument();
    });

    it('filters the list by the search query', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.type(screen.getByTestId('recent-search'), 'snake');
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(1));
        expect(screen.getByText('snake game')).toBeInTheDocument();
    });

    it('shows a no-matches message when the search excludes everything', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.type(screen.getByTestId('recent-search'), 'zzzznomatch');
        expect(screen.getByTestId('recent-empty')).toHaveTextContent('No matches');
    });

    it('loads a conversation when its row is clicked', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<RecentConversations onLoadConversation={onLoadConversation} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.click(screen.getByText('muxer flush bug'));
        expect(onLoadConversation).toHaveBeenCalledWith('c1');
    });

    it('clears the search box with the clear button', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        // No clear button until there's a query to clear.
        expect(screen.queryByTestId('recent-search-clear')).not.toBeInTheDocument();

        await user.type(screen.getByTestId('recent-search'), 'snake');
        expect(screen.getAllByTestId('recent-item')).toHaveLength(1);

        await user.click(screen.getByTestId('recent-search-clear'));
        expect(screen.getByTestId('recent-search')).toHaveValue('');
        expect(screen.getAllByTestId('recent-item')).toHaveLength(4);
        expect(screen.queryByTestId('recent-search-clear')).not.toBeInTheDocument();
    });

    it('marks the active conversation', async () => {
        render(<RecentConversations onLoadConversation={vi.fn()} activeConversationId="c2" />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));
        const active = screen.getByText('snake game').closest('[data-testid="recent-item"]');
        expect(active).toHaveAttribute('data-conversation-id', 'c2');
        expect(active.className).toMatch(/active/);
    });

    it('shows an empty state when there are no conversations', async () => {
        mockFetch([]);
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByTestId('recent-empty')).toBeInTheDocument());
        expect(screen.getByTestId('recent-empty')).toHaveTextContent('No conversations yet');
    });

    it('falls back to the first message when a conversation has no title', async () => {
        mockFetch([{ conversation_id: 'c9', first_message: 'hello there', started_at: isoAgo({ hours: 1 }) }]);
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('hello there')).toBeInTheDocument());
    });
});

describe('RecentConversations — context menu', () => {
    it('opens a per-row menu with pin, rename, and delete', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(within(menu).getByTestId('recent-menu-pin')).toHaveTextContent('Pin');
        expect(within(menu).getByTestId('recent-menu-rename')).toBeInTheDocument();
        expect(within(menu).getByTestId('recent-menu-delete')).toBeInTheDocument();
    });

    it('closes the menu when clicking outside', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('recent-menu')).not.toBeInTheDocument();
    });

    it('does not load the conversation when opening its menu', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<RecentConversations onLoadConversation={onLoadConversation} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(onLoadConversation).not.toHaveBeenCalled();
    });
});

describe('RecentConversations — delete', () => {
    it('deletes a conversation via the menu after a confirm click', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<RecentConversations onLoadConversation={onLoadConversation} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        const del = within(menu).getByTestId('recent-menu-delete');
        // First click arms, second click fires.
        await user.click(del);
        expect(screen.getAllByTestId('recent-item')).toHaveLength(4);
        await user.click(screen.getByTestId('recent-menu-delete'));

        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(3));
        expect(onLoadConversation).not.toHaveBeenCalled();
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c1',
            expect.objectContaining({ method: 'DELETE' }),
        );
    });

    it('opens a new conversation when the active one is deleted', async () => {
        const user = userEvent.setup();
        const onNewConversation = vi.fn();
        render(
            <RecentConversations
                onLoadConversation={vi.fn()}
                onNewConversation={onNewConversation}
                activeConversationId="c1"
            />,
        );
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        await user.click(screen.getByTestId('recent-menu-delete'));
        await user.click(screen.getByTestId('recent-menu-delete'));

        await waitFor(() => expect(onNewConversation).toHaveBeenCalledTimes(1));
    });

    it('does not open a new conversation when a non-active one is deleted', async () => {
        const user = userEvent.setup();
        const onNewConversation = vi.fn();
        render(
            <RecentConversations
                onLoadConversation={vi.fn()}
                onNewConversation={onNewConversation}
                activeConversationId="c2"
            />,
        );
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        await user.click(screen.getByTestId('recent-menu-delete'));
        await user.click(screen.getByTestId('recent-menu-delete'));

        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(3));
        expect(onNewConversation).not.toHaveBeenCalled();
    });
});

describe('RecentConversations — archive', () => {
    it('offers Archive in the per-row menu', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(within(menu).getByTestId('recent-menu-archive')).toBeInTheDocument();
    });

    it('archives a conversation, removing it from the list and posting to the archive endpoint', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        await user.click(within(menu).getByTestId('recent-menu-archive'));

        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(3));
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c1/archive',
            expect.objectContaining({ method: 'POST' }),
        );
    });

    it('opens a new conversation when the active one is archived', async () => {
        const user = userEvent.setup();
        const onNewConversation = vi.fn();
        render(
            <RecentConversations
                onLoadConversation={vi.fn()}
                onNewConversation={onNewConversation}
                activeConversationId="c1"
            />,
        );
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        await user.click(within(menu).getByTestId('recent-menu-archive'));

        await waitFor(() => expect(onNewConversation).toHaveBeenCalledTimes(1));
    });

    it('lazily loads and restores archived conversations', async () => {
        const user = userEvent.setup();
        // The archived endpoint returns one conversation; everything else
        // behaves like the default mock.
        global.fetch = vi.fn((url, opts) => {
            const method = opts?.method;
            if (typeof url === 'string' && url.endsWith('/archived')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve([
                        { conversation_id: 'a1', title: 'archived one', started_at: isoAgo({ days: 2 }) },
                    ]),
                });
            }
            if (method === 'DELETE' || method === 'PATCH' || method === 'POST') {
                return Promise.resolve({ ok: true, status: 204 });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve(SESSIONS) });
        });

        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        // The archived list isn't fetched until the section is expanded.
        expect(screen.queryByTestId('archived-item')).not.toBeInTheDocument();
        await user.click(screen.getByTestId('archived-toggle'));
        await waitFor(() => expect(screen.getByTestId('archived-item')).toBeInTheDocument());
        expect(screen.getByText('archived one')).toBeInTheDocument();

        // Restoring moves it back into the recents and posts to unarchive.
        await user.click(screen.getByTestId('archived-restore'));
        await waitFor(() => expect(screen.queryByTestId('archived-item')).not.toBeInTheDocument());
        expect(screen.getAllByTestId('recent-item')).toHaveLength(5);
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/a1/unarchive',
            expect.objectContaining({ method: 'POST' }),
        );
    });
});

describe('RecentConversations — pin', () => {
    it('pins a conversation into a Pinned section and persists it', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));
        expect(screen.queryByText('Pinned')).not.toBeInTheDocument();

        const row = screen.getByText('snake game').closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-pin'));

        // A Pinned section appears with the pinned conversation under it.
        const pinnedLabel = await screen.findByText('Pinned');
        expect(pinnedLabel).toBeInTheDocument();
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c2',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ pinned: true }),
            }),
        );
    });

    it('shows Unpin for an already-pinned conversation and unpins it', async () => {
        const user = userEvent.setup();
        mockFetch([
            { conversation_id: 'p1', title: 'pinned chat', started_at: isoAgo({ hours: 1 }), pinned: true },
            { conversation_id: 'c2', title: 'snake game', started_at: isoAgo({ hours: 3 }) },
        ]);
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Pinned')).toBeInTheDocument());

        const row = screen.getByText('pinned chat').closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        expect(within(menu).getByTestId('recent-menu-pin')).toHaveTextContent('Unpin');
        await user.click(within(menu).getByTestId('recent-menu-pin'));

        await waitFor(() => expect(screen.queryByText('Pinned')).not.toBeInTheDocument());
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/p1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ pinned: false }),
            }),
        );
    });
});

describe('RecentConversations — rename', () => {
    async function startRename(user, label) {
        const row = screen.getByText(label).closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-rename'));
        return screen.getByTestId('recent-rename-input');
    }

    it('renames inline and saves via the Rename button', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        await user.clear(input);
        await user.type(input, 'tetris clone');
        await user.click(screen.getByTestId('recent-rename-save'));

        await waitFor(() => expect(screen.getByText('tetris clone')).toBeInTheDocument());
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c2',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ title: 'tetris clone' }),
            }),
        );
    });

    it('saves on Enter', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        await user.clear(input);
        await user.type(input, 'pong{Enter}');

        await waitFor(() => expect(screen.getByText('pong')).toBeInTheDocument());
    });

    it('disables the Rename button until the text changes', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        expect(screen.getByTestId('recent-rename-save')).toBeDisabled();
        await user.type(input, '!');
        expect(screen.getByTestId('recent-rename-save')).toBeEnabled();
    });

    it('caps the input at 50 characters', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        expect(input).toHaveAttribute('maxLength', '50');
    });

    it('cancels on Escape without persisting', async () => {
        const user = userEvent.setup();
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        await user.clear(input);
        await user.type(input, 'discarded{Escape}');

        expect(screen.getByText('snake game')).toBeInTheDocument();
        expect(screen.queryByTestId('recent-rename-input')).not.toBeInTheDocument();
        expect(global.fetch).not.toHaveBeenCalledWith(
            expect.stringContaining('/api/conversations/sessions/c2'),
            expect.objectContaining({ method: 'PATCH' }),
        );
    });

    it('reverts to the first-message fallback when saved blank', async () => {
        const user = userEvent.setup();
        mockFetch([
            { conversation_id: 'c5', title: 'has a title', first_message: 'original prompt text', started_at: isoAgo({ hours: 1 }) },
        ]);
        render(<RecentConversations onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('has a title')).toBeInTheDocument());

        const input = await startRename(user, 'has a title');
        await user.clear(input);
        await user.click(screen.getByTestId('recent-rename-save'));

        await waitFor(() => expect(screen.getByText('original prompt text')).toBeInTheDocument());
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c5',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ title: '' }),
            }),
        );
    });
});
