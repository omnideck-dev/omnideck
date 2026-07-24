import { act, renderHook } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import useCustomAppWorkspace from '../useCustomAppWorkspace.jsx';

const APP = { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' };
const FILE_TAB = { id: 'file:/tmp/note.txt', label: 'note.txt', icon: <i /> };

function makePreview() {
    return {
        tabs: [FILE_TAB],
        openFile: vi.fn(),
        setActiveTab: vi.fn(),
        closeTab: vi.fn(),
    };
}

function setup({ homeAppSlug = null } = {}) {
    const preview = makePreview();
    const setDraft = vi.fn();
    const setView = vi.fn();
    const onHomeAppChange = vi.fn();
    const { result } = renderHook(() => useCustomAppWorkspace({
        preview,
        setDraft,
        setView,
        homeAppSlug,
        onHomeAppChange,
    }));
    return { result, preview, setDraft, setView, onHomeAppChange };
}

afterEach(() => vi.restoreAllMocks());

test('owns app presentation while adapting conversation preview tabs', () => {
    const { result, preview, setView } = setup({ homeAppSlug: 'text-lab' });

    act(() => result.current.openFull(APP));
    expect(result.current.layout).toBe('full');
    expect(result.current.activeTab).toBe('app:text-lab');
    expect(result.current.tabs.map((tab) => tab.id)).toEqual([
        'app:text-lab',
        'file:/tmp/note.txt',
    ]);

    act(() => result.current.openChat());
    expect(result.current.layout).toBe('split');
    expect(setView).toHaveBeenLastCalledWith('workspace');

    act(() => result.current.reload());
    expect(result.current.reloadSignal).toBe(1);
    act(() => result.current.openHome(APP));
    expect(result.current.layout).toBe('full');
    expect(result.current.origin).toBe('home');
    expect(result.current.reloadSignal).toBe(1);

    act(() => result.current.selectTab('file:/tmp/note.txt'));
    expect(result.current.activeTab).toBe('file:/tmp/note.txt');
    expect(preview.setActiveTab).toHaveBeenCalledWith('file:/tmp/note.txt');

    act(() => result.current.closeTab('file:/tmp/note.txt'));
    expect(preview.closeTab).toHaveBeenCalledWith('file:/tmp/note.txt');
    expect(result.current.activeTab).toBe('app:text-lab');
});

test('keeps an app open across previews and closes it only from its own tab', () => {
    const { result, preview, setView } = setup();
    act(() => result.current.openBesideChat(APP));

    act(() => result.current.openPreview({ filename: 'note.txt', path: '/tmp/note.txt' }));
    expect(preview.openFile).toHaveBeenCalledWith({ filename: 'note.txt', path: '/tmp/note.txt' });
    expect(result.current.activeTab).toBe('file:/tmp/note.txt');

    act(() => result.current.closeTab('app:text-lab'));
    expect(result.current.isOpen).toBe(false);
    expect(setView).toHaveBeenLastCalledWith('chat');
});

test('seeds the current chat with bounded app context', () => {
    const { result, setDraft } = setup();
    act(() => result.current.openFull(APP));
    act(() => result.current.composeInChat({ text: 'Review this', context: { draft: 'hello' } }));

    const updateDraft = setDraft.mock.calls[0][0];
    expect(updateDraft('Existing')).toContain('Context from Text Lab');
    expect(updateDraft('')).toContain('"hello"');
    expect(result.current.layout).toBe('split');
});

test('persists Home assignment without putting request logic in the toolbar', async () => {
    global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: async () => ({ home_app_slug: 'text-lab' }),
    }));
    const { result, onHomeAppChange } = setup();
    act(() => result.current.openFull(APP));

    await act(async () => result.current.toggleHome());

    expect(global.fetch).toHaveBeenCalledWith('/api/custom-apps/home', expect.objectContaining({
        method: 'PUT',
    }));
    expect(onHomeAppChange).toHaveBeenCalledWith('text-lab');
});
