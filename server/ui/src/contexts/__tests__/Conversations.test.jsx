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

// The list endpoint returns SESSIONS; the title endpoint returns a generated
// title so addStartedConversation's patch can be observed.
function mockFetch() {
    global.fetch = vi.fn((url) => {
        if (typeof url === 'string' && url.endsWith('/title')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve({ title: 'Generated Title' }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve(SESSIONS) });
    });
}

beforeEach(() => { mockFetch(); });
afterEach(() => {
    vi.restoreAllMocks();
    api = null;
});

describe('ConversationsProvider', () => {
    it('loads the list once on mount and never refetches it', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());
        const listCalls = global.fetch.mock.calls.filter(([u]) => u === '/api/conversations/sessions');
        expect(listCalls).toHaveLength(1);
    });

    it('addStartedConversation shows the row immediately, then fills in the generated title', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());

        act(() => api.addStartedConversation({ conversationId: 'c2', firstMessage: 'hi there' }));
        // Appears at the top immediately with the first-message fallback...
        expect(screen.getAllByTestId('row')[0]).toHaveTextContent('c2:hi there');
        // ...then the generated title lands without a refetch.
        await waitFor(() => expect(screen.getByText('c2:Generated Title')).toBeInTheDocument());
        const listCalls = global.fetch.mock.calls.filter(([u]) => u === '/api/conversations/sessions');
        expect(listCalls).toHaveLength(1);
    });

    it('addStartedConversation is deduped by id', async () => {
        render(<ConversationsProvider><Probe /></ConversationsProvider>);
        await waitFor(() => expect(screen.getByText('c1:one')).toBeInTheDocument());

        act(() => api.addStartedConversation({ conversationId: 'c2', firstMessage: 'hi' }));
        act(() => api.addStartedConversation({ conversationId: 'c2', firstMessage: 'dup' }));
        await waitFor(() => expect(screen.getByText('c2:Generated Title')).toBeInTheDocument());
        expect(screen.getAllByTestId('row')).toHaveLength(2);
    });
});
