import { act, render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import {
    WorkspaceProvider,
    useWorkspaceDispatch,
    useWorkspaceState,
} from '../WorkspaceState.jsx';

function renderWithProvider() {
    let dispatch;
    let state;

    function Inspector() {
        state = useWorkspaceState();
        dispatch = useWorkspaceDispatch();
        return null;
    }

    render(
        <WorkspaceProvider>
            <Inspector />
        </WorkspaceProvider>,
    );
    return {
        getState: () => state,
        dispatch: (action) => act(() => dispatch(action)),
    };
}

function started(agentId, parentAgentId = null) {
    return { type: 'WORKSPACE_AGENT_STARTED', agentId, parentAgentId };
}

const BROWSER_SNAPSHOT = {
    url: 'https://example.com',
    title: 'Example',
    screenshot: 'image-data',
    agentId: 'root-1',
    tabId: 1,
    openTabIds: [1],
};

const TERMINAL_EVENT = {
    cmd_id: 'command-1',
    cmd: 'echo hello',
    stdout: 'hello\n',
    stderr: null,
    exit_code: 0,
    status: 'complete',
    agentId: 'root-1',
};

const GENERATION_PREVIEW = {
    gen_id: 'generation-1',
    media_type: 'image',
    status: 'generating',
    step: 5,
    total_steps: 20,
    agentId: 'root-1',
};

describe('WorkspaceProvider', () => {
    it('stores browser, terminal, desktop, generation, and file state by agent', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
            snapshot: BROWSER_SNAPSHOT,
        });
        dispatch({ type: 'UPDATE_TERMINAL', agentId: 'root-1', event: TERMINAL_EVENT });
        dispatch({ type: 'UPDATE_DESKTOP_ACTIVE', agentId: 'root-1' });
        dispatch({
            type: 'UPDATE_GENERATION_PREVIEW',
            agentId: 'root-1',
            preview: GENERATION_PREVIEW,
        });
        dispatch({
            type: 'OPEN_FILE',
            agentId: 'root-1',
            item: { filename: 'report.md', path: '/tmp/report.md' },
        });

        expect(getState().byAgentId['root-1']).toMatchObject({
            browserTabs: { 1: BROWSER_SNAPSHOT },
            lastBrowserTabId: 1,
            desktopActive: true,
            generationPreview: GENERATION_PREVIEW,
            openFiles: [{ filename: 'report.md', path: '/tmp/report.md' }],
        });
        expect(getState().byAgentId['root-1'].terminalLines).toHaveLength(1);
    });

    it('carries root workspace state into the next root turn', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
            snapshot: BROWSER_SNAPSHOT,
        });
        dispatch({ type: 'UPDATE_TERMINAL', agentId: 'root-1', event: TERMINAL_EVENT });
        dispatch({
            type: 'OPEN_FILE',
            agentId: 'root-1',
            item: { filename: 'report.md', path: '/tmp/report.md' },
        });

        dispatch(started('root-2'));

        expect(getState().rootId).toBe('root-2');
        expect(getState().byAgentId['root-2'].browserTabs[1]).toEqual(BROWSER_SNAPSHOT);
        expect(getState().byAgentId['root-2'].terminalLines).toHaveLength(1);
        expect(getState().byAgentId['root-2'].openFiles).toHaveLength(1);
    });

    it('keeps sub-agent workspace state separate from the root', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch(started('child-1', 'root-1'));
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'child-1',
            snapshot: { ...BROWSER_SNAPSHOT, agentId: 'child-1' },
        });

        expect(getState().rootId).toBe('root-1');
        expect(getState().byAgentId['root-1'].browserTabs).toEqual({});
        expect(getState().byAgentId['child-1'].browserTabs[1].agentId).toBe('child-1');
    });

    it('reconciles closed browser tabs', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
            snapshot: { ...BROWSER_SNAPSHOT, openTabIds: [1, 2] },
        });
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
            snapshot: { ...BROWSER_SNAPSHOT, tabId: 2, openTabIds: [1, 2] },
        });
        dispatch({
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'root-1',
            snapshot: {
                url: '', title: '', screenshot: null, tabId: null, openTabIds: [2], agentId: 'root-1',
            },
        });

        expect(Object.keys(getState().byAgentId['root-1'].browserTabs)).toEqual(['2']);
    });

    it('merges generation progress and replaces a different generation', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({
            type: 'UPDATE_GENERATION_PREVIEW',
            agentId: 'root-1',
            preview: GENERATION_PREVIEW,
        });
        dispatch({
            type: 'UPDATE_GENERATION_PREVIEW',
            agentId: 'root-1',
            preview: { ...GENERATION_PREVIEW, step: 10 },
        });
        expect(getState().byAgentId['root-1'].generationPreview.step).toBe(10);

        dispatch({
            type: 'UPDATE_GENERATION_PREVIEW',
            agentId: 'root-1',
            preview: { ...GENERATION_PREVIEW, gen_id: 'generation-2', step: 1 },
        });
        expect(getState().byAgentId['root-1'].generationPreview.gen_id).toBe('generation-2');
    });

    it('keys files by full path and supports explicit close actions', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({ type: 'OPEN_FILE', agentId: 'root-1', item: { filename: 'X.md', path: '/a/X.md' } });
        dispatch({ type: 'OPEN_FILE', agentId: 'root-1', item: { filename: 'X.md', path: '/b/X.md' } });
        dispatch({ type: 'CLOSE_FILE', agentId: 'root-1', fileKey: '/a/X.md' });
        dispatch({ type: 'UPDATE_DESKTOP_ACTIVE', agentId: 'root-1' });
        dispatch({ type: 'UPDATE_GENERATION_PREVIEW', agentId: 'root-1', preview: GENERATION_PREVIEW });
        dispatch({ type: 'CLEAR_DESKTOP', agentId: 'root-1' });
        dispatch({ type: 'CLEAR_GENERATION_PREVIEW', agentId: 'root-1' });

        expect(getState().byAgentId['root-1'].openFiles).toEqual([
            { filename: 'X.md', path: '/b/X.md' },
        ]);
        expect(getState().byAgentId['root-1'].desktopActive).toBe(false);
        expect(getState().byAgentId['root-1'].generationPreview).toBeNull();
    });

    it('owns preview selection, split size, and fullscreen presentation', () => {
        const { getState, dispatch } = renderWithProvider();
        const file = { filename: 'report.md', path: '/tmp/report.md' };
        dispatch({ type: 'SELECT_PREVIEW_TAB', activeTab: 'browser' });
        dispatch({ type: 'SET_PREVIEW_SPLIT_POSITION', position: 55 });
        dispatch({ type: 'SET_FULLSCREEN_ITEM', item: { kind: 'file', file } });

        expect(getState().presentation).toEqual({
            activeTab: 'browser',
            splitPosition: 55,
            fullscreenItem: { kind: 'file', file },
        });
    });

    it('resets all workspace state', () => {
        const { getState, dispatch } = renderWithProvider();
        dispatch(started('root-1'));
        dispatch({ type: 'RESET' });
        expect(getState()).toEqual({
            byAgentId: {},
            rootId: null,
            restoredActiveTab: null,
            presentation: {
                activeTab: null,
                splitPosition: 40,
                fullscreenItem: null,
            },
        });
    });
});
