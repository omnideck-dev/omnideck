import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ArtifactsHubView from '../ArtifactsHubView.jsx';

const ARTIFACTS = [
    {
        id: 'a1', conversation_id: 'c1', path: '/home/computron/a.md', filename: 'a.md',
        content_type: 'text/markdown', agent_name: 'Claude',
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', status: 'present',
    },
    {
        id: 'a2', conversation_id: 'c2', path: '/home/computron/b.html', filename: 'b.html',
        content_type: 'text/html', agent_name: 'Claude',
        created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', status: 'present',
    },
];

let artifacts;

beforeEach(() => {
    artifacts = [...ARTIFACTS];
    global.fetch = vi.fn((url, opts) => {
        const u = String(url);
        const method = opts?.method || 'GET';
        if (u.startsWith('/api/artifacts') && method === 'GET') {
            return Promise.resolve({ ok: true, json: async () => ({ artifacts }) });
        }
        if (u.startsWith('/api/artifacts/') && method === 'DELETE') {
            return Promise.resolve({ ok: true, status: 204, json: async () => ({}) });
        }
        // FilePreview's file-content fetch
        return Promise.resolve({ ok: true, text: async () => '# hi', json: async () => ({}) });
    });
});

afterEach(() => { vi.restoreAllMocks(); });

function cardFor(filename) {
    return screen.getByText(filename).closest('[data-testid="artifact-card"]');
}

test('lists artifacts in the grid by default', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    expect(screen.getByText('b.html')).toBeInTheDocument();
    expect(screen.getAllByTestId('artifact-card')).toHaveLength(2);
});

test('toggles to the table view', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('layout-table'));
    expect(screen.getAllByTestId('artifact-row')).toHaveLength(2);
    expect(screen.getByText('a.md')).toBeInTheDocument();
});

test('search filters the list', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.change(screen.getByTestId('artifacts-search'), { target: { value: 'a.md' } });
    expect(screen.getByText('a.md')).toBeInTheDocument();
    expect(screen.queryByText('b.html')).not.toBeInTheDocument();
});

test('selecting an artifact renders the preview pane', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(cardFor('a.md'));
    const preview = await screen.findByTestId('artifact-preview');
    expect(within(preview).getByText('a.md')).toBeInTheDocument();
});

test('deleting a present artifact confirms then removes the row', async () => {
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());

    fireEvent.click(within(cardFor('a.md')).getByTestId('artifact-delete'));
    // present file -> confirmation dialog
    const dialog = await screen.findByTestId('delete-artifact-dialog');
    fireEvent.click(within(dialog).getByTestId('confirm-delete'));

    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
    const deleteCall = global.fetch.mock.calls.find(
        ([u, o]) => String(u).startsWith('/api/artifacts/a1') && o?.method === 'DELETE',
    );
    expect(deleteCall).toBeTruthy();
});

test('missing artifact deletes immediately without a dialog', async () => {
    artifacts = [{ ...ARTIFACTS[0], status: 'missing' }];
    render(<ArtifactsHubView />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());

    fireEvent.click(within(cardFor('a.md')).getByTestId('artifact-delete'));
    expect(screen.queryByTestId('delete-artifact-dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
});
