import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ArtifactsDrawer from '../ArtifactsDrawer.jsx';

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

const noop = () => {};

function rowFor(filename) {
    return screen.getByText(filename).closest('[data-testid="artifact-drawer-row"]');
}

test('lists the conversation-scoped artifacts by default', async () => {
    render(<ArtifactsDrawer conversationId="c1" onPreview={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    expect(screen.queryByText('b.html')).not.toBeInTheDocument();
});

test('the All toggle drops the conversation scope', async () => {
    render(<ArtifactsDrawer conversationId="c1" onPreview={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('drawer-scope-all'));
    await waitFor(() => expect(screen.getByText('b.html')).toBeInTheDocument());
});

test('selecting a present artifact opens the preview and closes the drawer', async () => {
    const onPreview = vi.fn();
    const onClose = vi.fn();
    render(<ArtifactsDrawer conversationId="c1" onPreview={onPreview} onClose={onClose} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(rowFor('a.md'));
    expect(onPreview).toHaveBeenCalledWith({
        filename: 'a.md', content_type: 'text/markdown', path: '/home/computron/a.md',
    });
    expect(onClose).toHaveBeenCalled();
});

test('deleting a present artifact confirms then removes the row', async () => {
    render(<ArtifactsDrawer conversationId="c1" onPreview={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(within(rowFor('a.md')).getByTestId('artifact-delete'));
    const dialog = await screen.findByTestId('delete-artifact-dialog');
    fireEvent.click(within(dialog).getByTestId('confirm-delete'));
    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
});

test('a missing artifact deletes immediately without a dialog', async () => {
    scoped = [{ ...A1, status: 'missing' }];
    render(<ArtifactsDrawer conversationId="c1" onPreview={noop} onClose={noop} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(within(rowFor('a.md')).getByTestId('artifact-delete'));
    expect(screen.queryByTestId('delete-artifact-dialog')).not.toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('a.md')).not.toBeInTheDocument());
});

test('Escape closes the drawer', async () => {
    const onClose = vi.fn();
    render(<ArtifactsDrawer conversationId="c1" onPreview={noop} onClose={onClose} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
});
