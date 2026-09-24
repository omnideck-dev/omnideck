import { createContext, useContext, useReducer } from 'react';
import { mergeTerminalEvent } from '../../utils/agentUtils.js';

const EMPTY_WORKSPACE = Object.freeze({
    browserTabs: {},
    lastBrowserTabId: null,
    terminalLines: [],
    desktopActive: false,
    generationPreview: null,
    openFiles: [],
});

const INITIAL_STATE = {
    byAgentId: {},
    rootId: null,
};

function newWorkspace(previous = null) {
    if (!previous) return { ...EMPTY_WORKSPACE };
    return {
        browserTabs: previous.browserTabs,
        lastBrowserTabId: previous.lastBrowserTabId,
        terminalLines: previous.terminalLines,
        desktopActive: previous.desktopActive,
        generationPreview: previous.generationPreview,
        openFiles: previous.openFiles,
    };
}

function updateWorkspace(state, agentId, update) {
    const current = state.byAgentId[agentId];
    if (!current) return state;
    return {
        ...state,
        byAgentId: {
            ...state.byAgentId,
            [agentId]: update(current),
        },
    };
}

function workspaceReducer(state, action) {
    switch (action.type) {
        case 'WORKSPACE_AGENT_STARTED': {
            const { agentId, parentAgentId } = action;
            const previousRoot = !parentAgentId && state.rootId
                ? state.byAgentId[state.rootId]
                : null;
            return {
                ...state,
                byAgentId: {
                    ...state.byAgentId,
                    [agentId]: newWorkspace(previousRoot),
                },
                rootId: parentAgentId ? state.rootId : agentId,
            };
        }

        case 'UPDATE_BROWSER_SNAPSHOT':
            return updateWorkspace(state, action.agentId, (workspace) => {
                const { snapshot } = action;
                const key = snapshot.tabId;
                const hasScreenshot = !!snapshot.screenshot;
                let browserTabs = hasScreenshot
                    ? { ...workspace.browserTabs, [key]: snapshot }
                    : workspace.browserTabs;
                if (Array.isArray(snapshot.openTabIds)) {
                    const keep = new Set(snapshot.openTabIds.map(String));
                    if (hasScreenshot) keep.add(String(key));
                    browserTabs = Object.fromEntries(
                        Object.entries(browserTabs).filter(([tabId]) => keep.has(tabId)),
                    );
                }
                return {
                    ...workspace,
                    browserTabs,
                    lastBrowserTabId: hasScreenshot ? key : workspace.lastBrowserTabId,
                };
            });

        case 'CLEAR_BROWSER_TABS':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                browserTabs: {},
                lastBrowserTabId: null,
            }));

        case 'UPDATE_TERMINAL':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                terminalLines: mergeTerminalEvent(workspace.terminalLines, action.event),
            }));

        case 'CLEAR_TERMINAL':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                terminalLines: [],
            }));

        case 'UPDATE_DESKTOP_ACTIVE':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                desktopActive: true,
            }));

        case 'CLEAR_DESKTOP':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                desktopActive: false,
            }));

        case 'UPDATE_GENERATION_PREVIEW':
            return updateWorkspace(state, action.agentId, (workspace) => {
                const previous = workspace.generationPreview;
                const preview = previous?.gen_id === action.preview.gen_id
                    ? { ...previous, ...action.preview }
                    : action.preview;
                return { ...workspace, generationPreview: preview };
            });

        case 'CLEAR_GENERATION_PREVIEW':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                generationPreview: null,
            }));

        case 'OPEN_FILE':
            return updateWorkspace(state, action.agentId, (workspace) => {
                const itemKey = action.item.path || action.item.filename;
                const existingIndex = workspace.openFiles.findIndex(
                    (file) => (file.path || file.filename) === itemKey,
                );
                const openFiles = existingIndex >= 0
                    ? workspace.openFiles.map((file, index) => (
                        index === existingIndex ? action.item : file
                    ))
                    : [...workspace.openFiles, action.item];
                return { ...workspace, openFiles };
            });

        case 'CLOSE_FILE':
            return updateWorkspace(state, action.agentId, (workspace) => ({
                ...workspace,
                openFiles: workspace.openFiles.filter(
                    (file) => (file.path || file.filename) !== action.fileKey,
                ),
            }));

        case 'RESET':
            return INITIAL_STATE;

        default:
            return state;
    }
}

const WorkspaceStateContext = createContext(null);
const WorkspaceDispatchContext = createContext(null);

export function WorkspaceProvider({ children }) {
    const [state, dispatch] = useReducer(workspaceReducer, INITIAL_STATE);
    return (
        <WorkspaceStateContext.Provider value={state}>
            <WorkspaceDispatchContext.Provider value={dispatch}>
                {children}
            </WorkspaceDispatchContext.Provider>
        </WorkspaceStateContext.Provider>
    );
}

export function useWorkspaceState() {
    const state = useContext(WorkspaceStateContext);
    if (state === null) throw new Error('useWorkspaceState must be used within WorkspaceProvider');
    return state;
}

export function useWorkspaceDispatch() {
    const dispatch = useContext(WorkspaceDispatchContext);
    if (dispatch === null) throw new Error('useWorkspaceDispatch must be used within WorkspaceProvider');
    return dispatch;
}
