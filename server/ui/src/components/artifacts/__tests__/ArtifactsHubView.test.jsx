import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import ArtifactsHubView from '../ArtifactsHubView.jsx';

const ARTIFACTS = [
    {
        id: 'a1', conversation_id: 'c1', path: '/home/computron/a.md', filename: 'a.md',
        content_type: 'text/markdown', agent_name: 'Claude', conversation_title: 'Conv One',
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', status: 'present',
    },
    {
        id: 'a2', conversation_id: 'c2', path: '/home/computron/b.html', filename: 'b.html',
        content_type: 'text/html', agent_name: 'Claude', conversation_title: 'Conv Two',
        created_at: '2026-01-02T00:00:00Z', updated_at: '2026-01-02T00:00:00Z', status: 'present',
    },
];

let artifacts;
let previewObserver;

class PreviewIntersectionObserver {
    constructor(callback, options) {
        this.callback = callback;
        this.options = options;
        this.nodes = new Set();
        previewObserver = this;
    }

    observe(node) {
        this.nodes.add(node);
    }

    unobserve(node) {
        this.nodes.delete(node);
    }

    disconnect() {
        this.nodes.clear();
    }

    intersect(node, isIntersecting) {
        this.callback([{ target: node, isIntersecting }]);
    }
}

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

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

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

test('selecting an artifact asks the Desktop to open its View', async () => {
    const onOpenArtifact = vi.fn();
    render(<ArtifactsHubView onOpenArtifact={onOpenArtifact} />);
    await waitFor(() => expect(screen.getByText('a.md')).toBeInTheDocument());
    fireEvent.click(cardFor('a.md'));
    expect(onOpenArtifact).toHaveBeenCalledWith(ARTIFACTS[0]);
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

test('mounts previews near the viewport and releases them when the tab is hidden', async () => {
    vi.stubGlobal('IntersectionObserver', PreviewIntersectionObserver);
    const { rerender } = render(<ArtifactsHubView visible />);
    await screen.findByText('b.html');

    const htmlSurface = screen.getByTestId('artifact-preview-a2');
    expect(previewObserver.options).toEqual({ rootMargin: '320px 0px' });
    expect(previewObserver.nodes.has(htmlSurface)).toBe(true);
    expect(htmlSurface.querySelector('iframe')).not.toBeInTheDocument();

    act(() => previewObserver.intersect(htmlSurface, true));
    const frame = await waitFor(() => {
        const element = htmlSurface.querySelector('iframe');
        expect(element).toBeInTheDocument();
        return element;
    });
    const skeleton = screen.getByTestId('artifact-preview-skeleton-a2');
    expect(skeleton).toHaveAttribute('data-hidden', 'false');

    fireEvent.load(frame);
    expect(skeleton).toHaveAttribute('data-hidden', 'true');

    fireEvent.change(screen.getByTestId('artifacts-search'), {
        target: { value: 'b.html' },
    });
    rerender(<ArtifactsHubView visible={false} />);
    expect(htmlSurface.querySelector('iframe')).not.toBeInTheDocument();
    expect(screen.getByTestId('artifacts-search')).toHaveValue('b.html');

    rerender(<ArtifactsHubView visible />);
    expect(screen.getByTestId('artifacts-search')).toHaveValue('b.html');
    act(() => previewObserver.intersect(htmlSurface, true));
    await waitFor(() => expect(htmlSurface.querySelector('iframe')).toBeInTheDocument());

    act(() => previewObserver.intersect(htmlSurface, false));
    expect(htmlSurface.querySelector('iframe')).not.toBeInTheDocument();
});

test('uses type-specific loading surfaces and immediate fallback icons', async () => {
    artifacts = [
        ARTIFACTS[0],
        {
            ...ARTIFACTS[0],
            id: 'image-1',
            path: '/home/computron/image.png',
            filename: 'image.png',
            content_type: 'image/png',
        },
        {
            ...ARTIFACTS[0],
            id: 'pdf-1',
            path: '/home/computron/brief.pdf',
            filename: 'brief.pdf',
            content_type: 'application/pdf',
        },
    ];
    vi.stubGlobal('IntersectionObserver', PreviewIntersectionObserver);
    render(<ArtifactsHubView />);
    await screen.findByText('image.png');

    const imageSurface = screen.getByTestId('artifact-preview-image-1');
    act(() => previewObserver.intersect(imageSurface, true));
    const image = imageSurface.querySelector('img');
    const imageSkeleton = screen.getByTestId('artifact-preview-skeleton-image-1');
    expect(image).toBeInTheDocument();
    expect(imageSkeleton).toHaveAttribute('data-hidden', 'false');
    fireEvent.load(image);
    expect(imageSkeleton).toHaveAttribute('data-hidden', 'true');

    const textSurface = screen.getByTestId('artifact-preview-a1');
    act(() => previewObserver.intersect(textSurface, true));
    expect(screen.getByTestId('artifact-preview-skeleton-a1'))
        .toBeInTheDocument();
    await waitFor(() => expect(textSurface.querySelector('pre')).toHaveTextContent('# hi'));
    expect(screen.getByTestId('artifact-preview-skeleton-a1'))
        .toHaveAttribute('data-hidden', 'true');

    const pdfSurface = screen.getByTestId('artifact-preview-pdf-1');
    act(() => previewObserver.intersect(pdfSurface, true));
    expect(pdfSurface.querySelector('.bi-filetype-pdf')).toBeInTheDocument();
    expect(within(pdfSurface).queryByTestId(/artifact-preview-skeleton/))
        .not.toBeInTheDocument();
});
