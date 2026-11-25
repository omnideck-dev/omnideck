import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import ActivityStreamProvider from '../../../app/ActivityStreamProvider.jsx';
import { AppEffectsProvider } from '../../../app/AppEffects.jsx';
import { ConversationCatalogProvider, useConversationCatalog } from '../ConversationCatalog.jsx';
import useArchivedConversations from '../useArchivedConversations.js';

const ACTIVE = [
    { conversation_id: 'c1', title: 'Plan the reunion', first_message: '', started_at: '2026-01-02T00:00:00Z', turn_count: 1, pinned: false, folder_id: null },
    { conversation_id: 'c2', title: 'Renew passports', first_message: '', started_at: '2026-01-01T00:00:00Z', turn_count: 1, pinned: false, folder_id: null },
];
const ARCHIVED = [
    { conversation_id: 'old', title: 'Old trip', first_message: '', started_at: '2025-01-01T00:00:00Z', turn_count: 3, pinned: false, folder_id: null },
];

let source;
let responses;

function summary(conversation_id, fields = {}) {
    return { conversation_id, title: '', first_message: '', started_at: '2026-01-03T00:00:00Z', turn_count: 1, pinned: false, folder_id: null, ...fields };
}

function emit(message) {
    act(() => source.onmessage({ data: JSON.stringify(message) }));
}

function listCalls(url) {
    return global.fetch.mock.calls.filter(([u]) => u === url).length;
}

function Providers({ children }) {
    return (
        <AppEffectsProvider>
            <ActivityStreamProvider>{children}</ActivityStreamProvider>
        </AppEffectsProvider>
    );
}

function Rows() {
    const { items } = useConversationCatalog();
    return (
        <ul>
            {items.map((c) => (
                <li key={c.conversation_id} data-testid="row">{c.conversation_id}:{c.title || c.first_message}{c.pinned ? ':pinned' : ''}</li>
            ))}
        </ul>
    );
}

function rows() {
    return screen.queryAllByTestId('row').map((row) => row.textContent);
}

async function renderCatalog() {
    render(<Providers><ConversationCatalogProvider><Rows /></ConversationCatalogProvider></Providers>);
    await waitFor(() => expect(rows()).toEqual(['c1:Plan the reunion', 'c2:Renew passports']));
}

beforeEach(() => {
    responses = { '/api/conversations/sessions': ACTIVE, '/api/conversations/archived': ARCHIVED, '/api/conversations/folders': [] };
    vi.stubGlobal('EventSource', class {
        constructor(url) {
            this.url = url;
            this.close = vi.fn();
            source = this;
        }
    });
    global.fetch = vi.fn((url) => Promise.resolve({ ok: true, json: () => Promise.resolve(responses[url]) }));
});
afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe('live chat list', () => {
    it('adds a chat started elsewhere to the top of the list', async () => {
        await renderCatalog();

        emit({ type: 'conversation_changed', conversation: summary('c3', { first_message: 'Book the vet' }), archived: false });

        expect(rows()).toEqual(['c3:Book the vet', 'c1:Plan the reunion', 'c2:Renew passports']);
    });

    it('updates a renamed or pinned chat in place', async () => {
        await renderCatalog();

        emit({ type: 'conversation_changed', conversation: { ...ACTIVE[1], title: 'Passports', pinned: true }, archived: false });

        expect(rows()).toEqual(['c1:Plan the reunion', 'c2:Passports:pinned']);
    });

    it('drops chats archived or deleted elsewhere', async () => {
        await renderCatalog();

        emit({ type: 'conversation_changed', conversation: ACTIVE[0], archived: true });
        emit({ type: 'conversation_removed', conversation_id: 'c2' });

        expect(rows()).toEqual([]);
    });

    it('refetches only when the stream reconnects, not on its first connection', async () => {
        await renderCatalog();

        emit({ type: 'conversation_resync' });
        expect(listCalls('/api/conversations/sessions')).toBe(1);

        responses['/api/conversations/sessions'] = [summary('c9', { title: 'Missed while offline' }), ...ACTIVE];
        emit({ type: 'conversation_resync' });

        await waitFor(() => expect(rows()[0]).toBe('c9:Missed while offline'));
        expect(listCalls('/api/conversations/sessions')).toBe(2);
        expect(listCalls('/api/conversations/folders')).toBe(2);
    });

    it('ignores malformed chat messages', async () => {
        const error = vi.spyOn(console, 'error').mockImplementation(() => {});
        await renderCatalog();

        emit({ type: 'conversation_changed', conversation: { title: 'no id' }, archived: false });
        emit({ type: 'conversation_removed' });

        expect(rows()).toEqual(['c1:Plan the reunion', 'c2:Renew passports']);
        expect(error).toHaveBeenCalledTimes(2);
    });
});

describe('live archived list', () => {
    async function renderArchived() {
        const view = renderHook(() => useArchivedConversations(), { wrapper: Providers });
        await waitFor(() => expect(view.result.current.archivedLoaded).toBe(true));
        return view;
    }

    const ids = (result) => result.current.archived.map((c) => c.conversation_id);

    it('adds chats archived elsewhere and drops chats restored or deleted elsewhere', async () => {
        const { result } = await renderArchived();
        expect(ids(result)).toEqual(['old']);

        emit({ type: 'conversation_changed', conversation: ACTIVE[0], archived: true });
        expect(ids(result)).toEqual(['c1', 'old']);

        emit({ type: 'conversation_changed', conversation: ACTIVE[0], archived: false });
        emit({ type: 'conversation_removed', conversation_id: 'old' });
        expect(ids(result)).toEqual([]);
    });

    it('reloads after the stream reconnects', async () => {
        const { result } = await renderArchived();

        emit({ type: 'conversation_resync' });
        responses['/api/conversations/archived'] = [];
        emit({ type: 'conversation_resync' });

        await waitFor(() => expect(ids(result)).toEqual([]));
        expect(listCalls('/api/conversations/archived')).toBe(2);
    });
});
