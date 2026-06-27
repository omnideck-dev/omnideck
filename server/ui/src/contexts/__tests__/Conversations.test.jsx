import { render, screen, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationsProvider, useConversations } from '../Conversations.jsx';

// Captures the live context value so tests can call its mutators directly.
let api = null;

function Probe() {
    api = useConversations();
    return (
        <ul data-testid="list">
            {api.items.map((c) => (
                <li key={c.conversation_id} data-testid="row">
                    {c.conversation_id}:{c.title || c.first_message || ''}
                </li>
            ))}
        </ul>
    );
}

const SESSIONS = [
    { conversation_id: 'c1', title: 'one', started_at: '2026-01-01T00:00:00Z' },
];

beforeEach(() => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true, json: () => Promise.resolve(SESSIONS),
    }));
});
afterEach(() => {
    vi.restoreAllMocks();
    api = null;
});

describe('ConversationsProvider', () => {
    it('loads the list once on mount and never refetches', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());
        expect(global.fetch).toHaveBeenCalledTimes(1);
        expect(global.fetch).toHaveBeenCalledWith('/api/conversations/sessions');
    });

    it('inserts a new conversation at the top, deduped by id', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());

        act(() => api.insertConversation({ conversation_id: 'c2', first_message: 'hi', title: '' }));
        expect(screen.getAllByTestId('row')[0]).toHaveTextContent('c2:hi');

        // Re-inserting the same id is a no-op, not a duplicate row.
        act(() => api.insertConversation({ conversation_id: 'c2', first_message: 'dup', title: '' }));
        expect(screen.getAllByTestId('row')).toHaveLength(2);
        // No refetch was triggered by the local mutations.
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('patches a conversation title in place', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());

        act(() => api.insertConversation({ conversation_id: 'c2', first_message: 'hi', title: '' }));
        act(() => api.patchConversationTitle('c2', 'Generated Title'));
        expect(screen.getByText('c2:Generated Title')).toBeInTheDocument();
    });
});
