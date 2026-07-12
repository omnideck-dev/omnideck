import { fireEvent, render as _render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ConversationsPanel from '../ConversationsPanel.jsx';
import { ConversationsProvider } from '../../contexts/Conversations.jsx';

// ConversationsPanel reads its list from the conversations context, so every
// render goes through the provider (which fetches the list on mount).
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

function mockFetch(sessions = SESSIONS, folders = []) {
    global.fetch = vi.fn((url, opts) => {
        const method = opts?.method;
        // The folders collection: GET lists, POST echoes back a created folder.
        if (typeof url === 'string' && url.endsWith('/folders')) {
            if (method === 'POST') {
                const name = JSON.parse(opts.body).name;
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ id: 'new-folder', name, icon: 'bi-folder', order: 99 }),
                });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve(folders) });
        }
        // Archived loads on mount; keep it empty by default.
        if (typeof url === 'string' && url.endsWith('/archived')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
        }
        // Everything else that mutates (rename/pin/folder PATCH, delete) is 204.
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

/** Open a folder header's 3-dot menu (by folder name) and return the menu. */
async function openFolderMenu(user, folderName) {
    const section = screen.getByText(folderName).closest('[data-testid="recent-section"]');
    await user.click(within(section).getByTestId('recent-folder-menu-trigger'));
    return screen.getByTestId('recent-folder-menu');
}

beforeEach(() => {
    // Fake only Date (not setTimeout/microtasks) so waitFor + userEvent still
    // run on real timers while the component reads the pinned "now".
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(FIXED_NOW);
    // Collapsed-section state persists to localStorage; clear it so each test
    // starts with every section expanded.
    localStorage.clear();
    mockFetch();
});
afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe('ConversationsPanel', () => {
    it('lists fetched conversations grouped by day', async () => {
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));
        expect(screen.getByText('Today')).toBeInTheDocument();
        expect(screen.getByText('Yesterday')).toBeInTheDocument();
        expect(screen.getByText('Earlier')).toBeInTheDocument();
    });

    it('filters the list by the search query', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.type(screen.getByTestId('recent-search'), 'snake');
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(1));
        expect(screen.getByText('snake game')).toBeInTheDocument();
    });

    it('searching shows a flat list with inline age and no section headers', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Today')).toBeInTheDocument());

        await user.type(screen.getByTestId('recent-search'), 'a');
        await waitFor(() => expect(screen.queryByTestId('recent-section')).not.toBeInTheDocument());
        // Every visible result carries an inline age stamp.
        const rows = screen.getAllByTestId('recent-item');
        expect(rows.length).toBeGreaterThan(0);
        expect(screen.getAllByTestId('recent-item-age')).toHaveLength(rows.length);
    });

    it('shows a no-matches message when the search excludes everything', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.type(screen.getByTestId('recent-search'), 'zzzznomatch');
        expect(screen.getByTestId('recent-empty')).toHaveTextContent('No matches');
    });

    it('loads a conversation when its row is clicked', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<ConversationsPanel onLoadConversation={onLoadConversation} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.click(screen.getByText('muxer flush bug'));
        expect(onLoadConversation).toHaveBeenCalledWith('c1');
    });

    it('clears the search box with the clear button', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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
        render(<ConversationsPanel onLoadConversation={vi.fn()} activeConversationId="c2" />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));
        const active = screen.getByText('snake game').closest('[data-testid="recent-item"]');
        expect(active).toHaveAttribute('data-conversation-id', 'c2');
        expect(active.className).toMatch(/active/);
    });

    it('shows an empty state when there are no conversations', async () => {
        mockFetch([]);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByTestId('recent-empty')).toBeInTheDocument());
        expect(screen.getByTestId('recent-empty')).toHaveTextContent('No conversations yet');
    });

    it('falls back to the first message when a conversation has no title', async () => {
        mockFetch([{ conversation_id: 'c9', first_message: 'hello there', started_at: isoAgo({ hours: 1 }) }]);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('hello there')).toBeInTheDocument());
    });
});

describe('ConversationsPanel — context menu', () => {
    it('opens a per-row menu with pin, rename, and delete', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(within(menu).getByTestId('recent-menu-pin')).toHaveTextContent('Pin');
        expect(within(menu).getByTestId('recent-menu-rename')).toBeInTheDocument();
        expect(within(menu).getByTestId('recent-menu-delete')).toBeInTheDocument();
    });

    it('closes the menu when clicking outside', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('recent-menu')).not.toBeInTheDocument();
    });

    it('does not load the conversation when opening its menu', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<ConversationsPanel onLoadConversation={onLoadConversation} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(onLoadConversation).not.toHaveBeenCalled();
    });
});

describe('ConversationsPanel — delete', () => {
    it('deletes a conversation via the menu after a confirm click', async () => {
        const user = userEvent.setup();
        const onLoadConversation = vi.fn();
        render(<ConversationsPanel onLoadConversation={onLoadConversation} />);
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
            <ConversationsPanel
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
            <ConversationsPanel
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

describe('ConversationsPanel — archive', () => {
    it('offers Archive in the per-row menu', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const menu = await openRowMenu(user, screen.getAllByTestId('recent-item')[0]);
        expect(within(menu).getByTestId('recent-menu-archive')).toBeInTheDocument();
    });

    it('archives a conversation, removing it from the list and posting to the archive endpoint', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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
            <ConversationsPanel
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

    it('shows the archived count while collapsed, then reveals + restores on expand', async () => {
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
            if (typeof url === 'string' && url.endsWith('/folders')) {
                return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
            }
            if (method === 'DELETE' || method === 'PATCH' || method === 'POST') {
                return Promise.resolve({ ok: true, status: 204 });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve(SESSIONS) });
        });

        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        // The count shows on the collapsed header (loaded on mount), but the
        // rows aren't rendered until the section is expanded.
        const archivedSection = screen.getByTestId('archived-section');
        await waitFor(() => expect(within(archivedSection).getByText('1')).toBeInTheDocument());
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

describe('ConversationsPanel — pin', () => {
    it('pins a conversation into a Pinned section and persists it', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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

describe('ConversationsPanel — rename', () => {
    async function startRename(user, label) {
        const row = screen.getByText(label).closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-rename'));
        return screen.getByTestId('recent-rename-input');
    }

    it('renames inline and saves via the Rename button', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        await user.clear(input);
        await user.type(input, 'pong{Enter}');

        await waitFor(() => expect(screen.getByText('pong')).toBeInTheDocument());
    });

    it('disables the Rename button until the text changes', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        expect(screen.getByTestId('recent-rename-save')).toBeDisabled();
        await user.type(input, '!');
        expect(screen.getByTestId('recent-rename-save')).toBeEnabled();
    });

    it('caps the input at 50 characters', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const input = await startRename(user, 'snake game');
        expect(input).toHaveAttribute('maxLength', '50');
    });

    it('cancels on Escape without persisting', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
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

describe('ConversationsPanel — folders', () => {
    const FOLDERS = [{ id: 'f1', name: 'Work', icon: 'bi-folder', order: 1 }];

    it('renders a folder section holding its filed conversation', async () => {
        mockFetch([
            { conversation_id: 'c1', title: 'in work', started_at: isoAgo({ hours: 1 }), folder_id: 'f1' },
            { conversation_id: 'c2', title: 'loose chat', started_at: isoAgo({ hours: 2 }) },
        ], FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);

        // The folder section appears (loaded async) with its name and holds the
        // filed chat; the unfiled chat stays in the date buckets.
        await screen.findByText('Work');
        const folderSection = screen.getByText('Work').closest('[data-testid="recent-section"]');
        expect(folderSection).toHaveAttribute('data-section', 'folder:f1');
        expect(within(folderSection).getByText('in work')).toBeInTheDocument();
        const workRow = screen.getByText('in work').closest('[data-testid="recent-item"]');
        expect(workRow).toHaveAttribute('data-folder-id', 'f1');
        expect(screen.getByText('Today')).toBeInTheDocument();
    });

    it('moves a conversation into a folder from the menu', async () => {
        const user = userEvent.setup();
        mockFetch(SESSIONS, FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        const row = screen.getByText('muxer flush bug').closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-move'));
        await user.click(screen.getByTestId('recent-menu-folder-option'));

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ folder_id: 'f1' }),
            }),
        );
        // The row now carries the folder tag.
        await waitFor(() => {
            const moved = screen.getByText('muxer flush bug').closest('[data-testid="recent-item"]');
            expect(moved).toHaveAttribute('data-folder-id', 'f1');
        });
    });

    it('unpins a pinned conversation when it is moved into a folder', async () => {
        const user = userEvent.setup();
        mockFetch([
            { conversation_id: 'p1', title: 'pinned chat', started_at: isoAgo({ hours: 1 }), pinned: true },
        ], FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Pinned')).toBeInTheDocument());

        const row = screen.getByText('pinned chat').closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-move'));
        await user.click(screen.getByTestId('recent-menu-folder-option'));

        // The row is filed and no longer pinned, so the Pinned section is gone
        // and the row now lives under its folder.
        await waitFor(() => expect(screen.queryByText('Pinned')).not.toBeInTheDocument());
        const moved = screen.getByText('pinned chat').closest('[data-testid="recent-item"]');
        expect(moved).toHaveAttribute('data-folder-id', 'f1');
        expect(moved).toHaveAttribute('data-pinned', 'false');
    });

    it('removes a conversation from its folder', async () => {
        const user = userEvent.setup();
        mockFetch([
            { conversation_id: 'c1', title: 'in work', started_at: isoAgo({ hours: 1 }), folder_id: 'f1' },
        ], FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('in work')).toBeInTheDocument());

        const row = screen.getByText('in work').closest('[data-testid="recent-item"]');
        const menu = await openRowMenu(user, row);
        await user.click(within(menu).getByTestId('recent-menu-move'));
        await user.click(screen.getByTestId('recent-menu-folder-remove'));

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/sessions/c1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ folder_id: null }),
            }),
        );
    });

    it('creates a folder from the new-folder button', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        await user.click(screen.getByTestId('recent-new-folder'));
        const input = screen.getByTestId('recent-new-folder-input');
        await user.type(input, 'Ideas{Enter}');

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/folders',
            expect.objectContaining({
                method: 'POST',
                body: JSON.stringify({ name: 'Ideas' }),
            }),
        );
        // The created folder shows up as a section.
        await waitFor(() => expect(screen.getByText('Ideas')).toBeInTheDocument());
    });

    it('renames a folder from the folder menu', async () => {
        const user = userEvent.setup();
        mockFetch(SESSIONS, FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument());

        const menu = await openFolderMenu(user, 'Work');
        await user.click(within(menu).getByTestId('recent-folder-menu-rename'));
        const input = screen.getByTestId('recent-folder-rename-input');
        await user.clear(input);
        await user.type(input, 'Job{Enter}');

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/folders/f1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ name: 'Job' }),
            }),
        );
        await waitFor(() => expect(screen.getByText('Job')).toBeInTheDocument());
    });

    it('deletes a folder from the folder menu and returns its chat to the date buckets', async () => {
        const user = userEvent.setup();
        mockFetch([
            { conversation_id: 'c1', title: 'in work', started_at: isoAgo({ hours: 1 }), folder_id: 'f1' },
        ], FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument());

        const menu = await openFolderMenu(user, 'Work');
        const del = within(menu).getByTestId('recent-folder-menu-delete');
        await user.click(del); // arms
        await user.click(screen.getByTestId('recent-folder-menu-delete')); // confirms

        await waitFor(() => expect(screen.queryByText('Work')).not.toBeInTheDocument());
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/folders/f1',
            expect.objectContaining({ method: 'DELETE' }),
        );
        // The chat is still listed — now under a date bucket.
        const row = screen.getByText('in work').closest('[data-testid="recent-item"]');
        expect(row).toHaveAttribute('data-folder-id', '');
    });

    it('changes a folder icon via the folder menu → icon picker', async () => {
        const user = userEvent.setup();
        mockFetch(SESSIONS, FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument());

        const menu = await openFolderMenu(user, 'Work');
        await user.click(within(menu).getByTestId('recent-folder-menu-icon'));
        const picker = await screen.findByTestId('recent-icon-picker');
        await user.click(picker.querySelector('[data-icon="bi-star"]'));

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/conversations/folders/f1',
            expect.objectContaining({
                method: 'PATCH',
                body: JSON.stringify({ icon: 'bi-star' }),
            }),
        );
    });

    it('closes the folder menu when its trigger is clicked again', async () => {
        const user = userEvent.setup();
        mockFetch(SESSIONS, FOLDERS);
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Work')).toBeInTheDocument());

        const section = screen.getByText('Work').closest('[data-testid="recent-section"]');
        const trigger = within(section).getByTestId('recent-folder-menu-trigger');
        await user.click(trigger);
        expect(screen.getByTestId('recent-folder-menu')).toBeInTheDocument();
        await user.click(trigger);
        expect(screen.queryByTestId('recent-folder-menu')).not.toBeInTheDocument();
    });

    it('collapses a section and persists it to localStorage', async () => {
        const user = userEvent.setup();
        render(<ConversationsPanel onLoadConversation={vi.fn()} />);
        await waitFor(() => expect(screen.getAllByTestId('recent-item')).toHaveLength(4));

        // "Today" holds two of the seeded chats; collapsing hides them.
        const todaySection = screen.getByText('Today').closest('[data-testid="recent-section"]');
        await user.click(within(todaySection).getByTestId('recent-section-toggle'));

        await waitFor(() => expect(within(todaySection).queryByTestId('recent-item')).not.toBeInTheDocument());
        expect(JSON.parse(localStorage.getItem('omnideck_sidebar_collapsed_sections'))).toContain('Today');
    });
});
