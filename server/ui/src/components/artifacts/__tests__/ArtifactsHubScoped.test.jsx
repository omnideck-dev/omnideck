import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ArtifactsHubView from '../ArtifactsHubView.jsx';

const A1 = {
    id: 'a1', conversation_id: 'c1', path: '/home/computron/a.md', filename: 'a.md',
    content_type: 'text/markdown', conversation_title: 'Conv One',
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', status: 'present',
};
const A2 = {
    id: 'a2', conversation_id: 'c2', path: '/home/computron/b.html', filename: 'b.html',
    content_type: 'text/html', conversation_title: 'Conv Two',
    created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', status: 'present',
};

let scoped;

beforeEach(() => {
    scoped = [A1];
    global.fetch = vi.fn((url, opts) => {
        const u = String(url);
        const method = opts?.method || 'GET';
        if (u.startsWith('/api/artifacts/') && method === 'DELETE') {
            return Promise.resolve({ ok: true, status: 204, json: async () => ({}) });
        }
        if (u.startsWith('/api/artifacts') && method === 'GET') {
            // Scoped query returns only this conversation; unscoped returns all.
            const list = u.includes('conversation_id=') ? scoped : [A1, A2];
            return Promise.resolve({ ok: true, json: async () => ({ artifacts: list }) });
        }
        return Promise.resolve({ ok: true, text: async () => '# hi', json: async () => ({}) });
    });
});

afterEach(() => { vi.restoreAllMocks(); });

function rowFor(filename) {
    return screen.getByText(filename).closest('[data-testid="artifact-card"]');
}

test('lists only artifacts from the supplied conversation scope', async () => {
    render(<ArtifactsHubView conversationId="c1" />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    expect(screen.queryByText('b.html')).not.toBeInTheDocument();
    expect(screen.getByTestId('artifacts-hub')).toHaveAttribute(
        'data-conversation-id',
        'c1',
    );
});

test('the same hub is unscoped when no conversation is supplied', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('b.html')).toBeInTheDocument());
    expect(screen.getByText('a.md')).toBeInTheDocument();
});

test('selecting a present artifact asks the Desktop to open a View', async () => {
    const onOpenArtifact = vi.fn();
    render(
        <ArtifactsHubView
            conversationId="c1"
            onOpenArtifact={onOpenArtifact}
        />,
    );
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(rowFor('a.md'));
    expect(onOpenArtifact).toHaveBeenCalledWith(A1);
});

test('deleting a present artifact confirms then removes the row', async () => {
    render(<ArtifactsHubView conversationId="c1" />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(within(rowFor('a.md')).getByTestId('artifact-delete'));
    const dialog = await screen.findByTestId('delete-artifact-dialog');
    fireEvent.click(within(dialog).getByTestId('confirm-delete'));
    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
});

test('a missing artifact deletes immediately without a dialog', async () => {
    scoped = [{ ...A1, status: 'missing' }];
    render(<ArtifactsHubView conversationId="c1" />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(within(rowFor('a.md')).getByTestId('artifact-delete'));
    expect(screen.queryByTestId('delete-artifact-dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
});

test('uses the scoped artifacts endpoint', async () => {
    render(<ArtifactsHubView conversationId="c1" />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
        '/api/artifacts?conversation_id=c1',
    );
});

test('offers a way to clear the conversation filter', async () => {
    const onClearConversationFilter = vi.fn();
    render(
        <ArtifactsHubView
            conversationId="c1"
            onClearConversationFilter={onClearConversationFilter}
        />,
    );
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId(
        'artifacts-clear-conversation-filter',
    ));

    expect(onClearConversationFilter).toHaveBeenCalledTimes(1);
});
