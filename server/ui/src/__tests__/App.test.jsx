import { render, screen, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AppDataProvider } from '../contexts/AppData.jsx';

// Minimal 1x1 transparent PNG
const TINY_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADElEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==';

// ── Mock heavy child components ─────────────────────────────────────
// We only care about which panels / views are mounted, not their internals.

vi.mock('../components/ChatPanel.jsx', () => ({
    default: ({ turns, isStreaming, networkActivated, networkAgentCount, onOpenNetwork, draft }) => (
        <div data-testid="chat-panel">
            Chat
            <span data-testid="chat-messages">{turns?.length || 0} messages</span>
            <span data-testid="chat-streaming">{isStreaming ? 'streaming' : 'idle'}</span>
            <span data-testid="chat-draft">{draft}</span>
            {networkActivated && (
                <button data-testid="network-indicator" onClick={onOpenNetwork}>
                    {networkAgentCount} agents
                </button>
            )}
        </div>
    ),
}));

vi.mock('../components/BrowserPreview.jsx', () => ({
    default: ({ tabs }) => tabs?.length
        ? <div data-testid="browser-preview">Browser: {tabs[0].snapshot.url}</div>
        : null,
}));

vi.mock('../components/TerminalOutput.jsx', () => ({
    default: ({ lines }) => lines?.length
        ? <div data-testid="terminal-panel">Terminal ({lines.length} cmds)</div>
        : null,
}));

vi.mock('../components/DesktopPreview.jsx', () => ({
    default: ({ visible }) => visible
        ? <div data-testid="desktop-preview">Desktop</div>
        : null,
}));

vi.mock('../components/GenerationPreview.jsx', () => ({
    default: ({ preview }) => preview
        ? <div data-testid="generation-preview">Generation: {preview.status}</div>
        : null,
}));

vi.mock('../components/AgentNetwork.jsx', () => ({
    default: ({ onClose, onSelectAgent }) => (
        <div data-testid="agent-network">
            Network Graph
            <button data-testid="network-select-agent" onClick={() => onSelectAgent('s1')}>Select</button>
            {onClose && <button data-testid="network-close" onClick={onClose}>Close</button>}
        </div>
    ),
}));

vi.mock('../components/AgentActivityView.jsx', () => ({
    default: ({ onBack }) => (
        <div data-testid="agent-activity-view">
            Activity View
            <button data-testid="activity-back" onClick={onBack}>Back</button>
        </div>
    ),
}));

vi.mock('../components/Sidebar.jsx', () => ({
    default: ({ activePanel, onPanelToggle, onNewConversation, onLoadConversation }) => (
        <div data-testid="sidebar">
            <span data-testid="sidebar-active-panel">{activePanel || 'chat'}</span>
            Sidebar
            <button data-testid="open-settings" onClick={() => onPanelToggle('settings')}>Settings</button>
            <button data-testid="open-routines" onClick={() => onPanelToggle('routines')}>Routines</button>
            <button data-testid="open-agents" onClick={() => onPanelToggle('agents')}>Agents</button>
            <button data-testid="open-apps" onClick={() => onPanelToggle('apps')}>Apps</button>
            <button data-testid="close-panel" onClick={() => onPanelToggle(null)}>Close panel</button>
            <button data-testid="new-chat" onClick={onNewConversation}>New chat</button>
            <button data-testid="load-conversation" onClick={() => onLoadConversation('conv-1')}>Load</button>
        </div>
    ),
}));

vi.mock('../components/TabbedPane.jsx', () => ({
    default: ({ children, tabs = [], onCloseTab, actions }) => (
        <div data-testid="preview-panel">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    data-testid={`close-tab-${tab.id}`}
                    onClick={() => onCloseTab?.(tab.id)}
                >
                    Close {tab.label}
                </button>
            ))}
            {actions}
            {children}
        </div>
    ),
}));

vi.mock('../components/SplitHandle.jsx', () => ({
    default: () => <div data-testid="split-handle" />,
}));

vi.mock('../components/FilePreview.jsx', () => ({
    default: ({ item, fullscreen }) => (fullscreen
        ? <div data-testid="fullscreen-preview" />
        : <div data-testid="file-preview-inline">{item?.filename}</div>),
}));

vi.mock('../components/BrowserFullscreen.jsx', () => ({
    default: () => <div data-testid="browser-fullscreen" />,
}));

vi.mock('../components/SettingsPage.jsx', () => ({
    default: () => <div data-testid="settings-page">Settings</div>,
}));

vi.mock('../components/apps/AppsView.jsx', () => ({
    default: ({ onOpenApp, onOpenAppInDock }) => (
        <div data-testid="apps-view">
            Apps
            <button data-testid="mock-open-app-full" onClick={() => onOpenApp({
                slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts',
            })}>Open full</button>
            <button data-testid="mock-open-app-docked" onClick={() => onOpenAppInDock({
                slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts',
            })}>Open split</button>
        </div>
    ),
}));

vi.mock('../components/apps/CustomAppHost.jsx', () => ({
    default: ({ app, active, onComposeChat }) => (
        <div data-testid="custom-app-frame" data-active={active ? 'true' : 'false'}>
            {app.title}
            <button data-testid="mock-workspace-compose" onClick={() => onComposeChat({
                text: 'Review this', context: { text: 'Draft' },
            })}>Compose</button>
        </div>
    ),
}));

vi.mock('../components/routines/RoutinesView.jsx', () => ({
    default: () => <div data-testid="routines-view">Routines</div>,
}));

vi.mock('../hooks/useRoutines.js', () => ({
    default: () => ({
        routines: [],
        runnerStatus: null,
        selectedRoutineId: null,
        setSelectedRoutineId: vi.fn(),
        deleteRoutine: vi.fn(),
        deleteRun: vi.fn(),
        pauseRoutine: vi.fn(),
        resumeRoutine: vi.fn(),
        triggerRoutine: vi.fn(),
        fetchRoutineDetail: vi.fn(),
    }),
}));

vi.mock('../components/SystemSettings.jsx', () => ({
    default: () => <div>SystemSettings</div>,
}));

vi.mock('../components/agents/AgentsView.jsx', () => ({
    default: () => <div data-testid="agents-view">Agents</div>,
}));

vi.mock('../components/SetupWizard.jsx', () => ({
    default: () => <div data-testid="setup-wizard">Setup Wizard</div>,
}));

vi.mock('../hooks/useAgentProfiles.js', () => ({
    default: () => ({
        profiles: [],
        selectedProfileId: null,
        setSelectedProfileId: vi.fn(),
        createProfile: vi.fn(),
        updateProfile: vi.fn(),
        deleteProfile: vi.fn(),
        duplicateProfile: vi.fn(),
        revision: 0,
    }),
}));

// Mutable holder so individual tests can simulate an in-progress stream.
// Reset to defaults in beforeEach.
const streamMock = vi.hoisted(() => {
    const makeDefault = () => ({
        turns: [],
        isStreaming: false,
        sendMessage: () => {},
        sendNudge: () => {},
        stopGeneration: () => {},
        loadConversation: () => true,
        newConversation: () => {},
        activeConversationId: null,
        savePreviewState: () => {},
    });
    return { makeDefault, value: makeDefault() };
});

vi.mock('../features/conversation/session/useConversationSessionController.js', () => ({
    default: () => streamMock.value,
}));

vi.mock('../hooks/useModelSettings.js', () => ({
    default: () => ({
        selectedModel: 'test',
        contextKb: '',
        think: false,
        temperature: '',
        topK: '',
        topP: '',
        repeatPenalty: '',
        numPredict: '',
    }),
}));

vi.mock('../components/ToastProvider.jsx', () => ({
    useToast: () => ({ addToast: vi.fn() }),
}));

// ── Import after mocks ──────────────────────────────────────────────
// Dynamic import so vi.mock calls are hoisted before it runs.
const { default: App } = await import('../App.jsx');

let capturedDispatch = null;
let capturedWorkspaceDispatch = null;

// Capture agent actions from inside the app's provider.
vi.mock('../features/agent/AgentState.jsx', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useAgentDispatch: () => {
            const dispatch = actual.useAgentDispatch();
            capturedDispatch = dispatch;
            return dispatch;
        },
    };
});

vi.mock('../features/workspace/WorkspaceState.jsx', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useWorkspaceDispatch: () => {
            const dispatch = actual.useWorkspaceDispatch();
            capturedWorkspaceDispatch = dispatch;
            return dispatch;
        },
    };
});

async function renderApp() {
    capturedDispatch = null;
    capturedWorkspaceDispatch = null;
    let result;
    await act(async () => {
        result = render(
            <AppDataProvider>
                <App />
            </AppDataProvider>,
        );
    });

    const dispatch = (action) => {
        act(() => {
            capturedDispatch(action);
            const workspaceAction = action.type === 'AGENT_STARTED'
                ? {
                    type: 'WORKSPACE_AGENT_STARTED',
                    agentId: action.agentId,
                    parentAgentId: action.parentAgentId,
                }
                : action;
            capturedWorkspaceDispatch(workspaceAction);
        });
    };

    return { dispatch, ...result };
}

function startRoot(dispatch, id, { name = 'omnideck' } = {}) {
    dispatch({
        type: 'AGENT_STARTED',
        agentId: id,
        agentName: name,
        parentAgentId: null,
        instruction: '',
        timestamp: Date.now(),
    });
}

function startSubAgent(dispatch, id, parentId, { name = 'browser_agent' } = {}) {
    dispatch({
        type: 'AGENT_STARTED',
        agentId: id,
        agentName: name,
        parentAgentId: parentId,
        instruction: '',
        timestamp: Date.now(),
    });
}

// ─────────────────────────────────────────────────────────────────────

describe('App view transitions', () => {
    beforeEach(() => {
        capturedDispatch = null;
        capturedWorkspaceDispatch = null;
        streamMock.value = streamMock.makeDefault();
        // Mock the fetches App's children make on mount so the setup
        // wizard resolves and nothing else trips on a missing endpoint.
        globalThis.fetch = vi.fn((url) => {
            if (url === '/api/settings') {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ setup_complete: true }) });
            }
            if (url === '/api/providers') {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
            }
            if (url === '/api/profiles') {
                return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
            }
            if (url.startsWith('/api/models')) {
                return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
    });

    // ── Simple chat view (no sub-agents, no previews) ───────────────

    describe('simple chat view', () => {
        it('keeps the desktop unmounted until setup is complete', async () => {
            globalThis.fetch = vi.fn((url) => {
                if (url === '/api/settings') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({ setup_complete: false }),
                    });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
            });

            await renderApp();

            expect(screen.getByTestId('setup-wizard')).toBeInTheDocument();
            expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument();
            expect(screen.queryByTestId('sidebar')).not.toBeInTheDocument();
        });

        it('shows chat panel on initial render', async () => {
            await renderApp();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('does not show network graph initially', async () => {
            await renderApp();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
        });

        it('does not show activity view initially', async () => {
            await renderApp();
            expect(screen.queryByTestId('agent-activity-view')).not.toBeInTheDocument();
        });

        it('lands on a docked custom app when Custom Apps are enabled', async () => {
            globalThis.fetch = vi.fn((url) => {
                if (url === '/api/settings') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({ setup_complete: true, home_app_slug: 'text-lab' }),
                    });
                }
                if (url === '/api/features') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ custom_apps: true }) });
                }
                if (url === '/api/custom-apps') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            apps: [{ slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' }],
                            home_app_slug: 'text-lab',
                        }),
                    });
                }
                if (url === '/api/providers') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
                }
                if (url === '/api/profiles') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
                }
                if (url.startsWith('/api/models')) {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
            });

            await renderApp();
            expect(await screen.findByTestId('home-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
        });
    });

    describe('desktop Custom App dock', () => {
        beforeEach(() => {
            globalThis.fetch = vi.fn((url) => {
                if (url === '/api/settings') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ setup_complete: true }) });
                }
                if (url === '/api/features') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ custom_apps: true }) });
                }
                if (url === '/api/providers') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
                }
                if (url === '/api/profiles') {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
                }
                if (url.startsWith('/api/models')) {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
            });
        });

        it('moves a full app beside the current chat, survives New chat, and can close', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));

            const customApp = screen.getByTestId('desktop-dock');
            expect(customApp).toHaveAttribute('data-layout', 'expanded');
            expect(customApp).toHaveAttribute('data-visible', 'true');

            fireEvent.click(screen.getByTestId('custom-app-chat'));
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');

            fireEvent.click(screen.getByTestId('close-tab-custom-app:text-lab'));
            expect(screen.queryByTestId('desktop-dock')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('opens the current chat and seeds its composer from explicit app context', async () => {
            const setDraft = vi.fn();
            streamMock.value = { ...streamMock.makeDefault(), draft: '', setDraft };
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId('mock-workspace-compose'));

            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
            expect(setDraft).toHaveBeenCalledOnce();
            const updateDraft = setDraft.mock.calls[0][0];
            expect(updateDraft('Existing draft')).toContain('Context from Text Lab');
            expect(updateDraft('')).toContain('"Draft"');
        });

        it('moves a docked app back to expanded presentation', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-docked'));

            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
            fireEvent.click(screen.getByTestId('custom-app-expand'));
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'expanded');

            fireEvent.click(screen.getByTestId('custom-app-close'));
            expect(screen.queryByTestId('desktop-dock')).not.toBeInTheDocument();
        });

        it('keeps the Custom App mounted while another desktop page hides it', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));

            const frame = screen.getByTestId('custom-app-frame');
            fireEvent.click(screen.getByTestId('open-settings'));
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-visible', 'false');
            expect(frame).toBeInTheDocument();
            expect(frame).toHaveAttribute('data-active', 'false');

            fireEvent.click(screen.getByTestId('close-panel'));
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
            expect(screen.getByTestId('custom-app-frame')).toBe(frame);
        });

        it('keeps the Custom App docked when loading a conversation', async () => {
            const loadConversation = vi.fn(() => true);
            streamMock.value = { ...streamMock.makeDefault(), loadConversation };
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-docked'));

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));

            expect(loadConversation).toHaveBeenCalledWith('conv-1');
            expect(screen.getByTestId('desktop-dock')).toHaveAttribute('data-layout', 'docked');
        });

        it('does not leave Apps highlighted after entering an app workspace', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('apps');

            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('chat');

            fireEvent.click(screen.getByTestId('custom-app-chat'));
            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('chat');
        });
    });

    // ── Simple chat + preview panels ────────────────────────────────

    describe('simple chat with preview panels', () => {
        it('shows browser preview alongside chat when snapshot arrives', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });

            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();
        });

        it('shows terminal panel alongside chat', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_TERMINAL',
                agentId: 'r1',
                event: { cmd_id: 'c1', cmd: 'ls', stdout: 'out\n', status: 'complete' },
            });

            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();
        });

        it('shows generation preview alongside chat', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_GENERATION_PREVIEW',
                agentId: 'r1',
                preview: { gen_id: 'g1', media_type: 'image', status: 'generating', step: 5, total_steps: 20 },
            });

            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('generation-preview')).toBeInTheDocument();
        });

        it('previews persist into second turn', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });

            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();

            // Second turn — new root agent
            startRoot(dispatch, 'r2');

            // Browser preview should still be visible (carried over)
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();
        });

        it('terminal lines persist into second turn', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_TERMINAL',
                agentId: 'r1',
                event: { cmd_id: 'c1', cmd: 'ls', stdout: 'out\n', status: 'complete' },
            });

            expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();

            startRoot(dispatch, 'r2');
            expect(screen.getByTestId('terminal-panel')).toBeInTheDocument();
        });

        it('generation preview persists into second turn', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_GENERATION_PREVIEW',
                agentId: 'r1',
                preview: { gen_id: 'g1', media_type: 'image', status: 'complete' },
            });

            expect(screen.getByTestId('generation-preview')).toBeInTheDocument();

            startRoot(dispatch, 'r2');
            expect(screen.getByTestId('generation-preview')).toBeInTheDocument();
        });

        it('new browser snapshot replaces old one in second turn', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://first.com', title: 'First', screenshot: TINY_PNG, tabId: 1 },
            });

            startRoot(dispatch, 'r2');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r2',
                snapshot: { url: 'https://second.com', title: 'Second', screenshot: TINY_PNG, tabId: 1 },
            });

            expect(screen.getByText('Browser: https://second.com')).toBeInTheDocument();
        });
    });

    // ── Network view (sub-agents) ───────────────────────────────────

    describe('network view', () => {
        it('does not auto-show network when sub-agent spawns; shows indicator instead', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');

            // Network is NOT auto-shown — chat stays visible
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            // Indicator appears so user can navigate to network
            expect(screen.getByTestId('network-indicator')).toBeInTheDocument();
        });

        it('shows network when indicator is clicked', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');

            act(() => fireEvent.click(screen.getByTestId('network-indicator')));

            expect(screen.getByTestId('agent-network')).toBeInTheDocument();
        });

        it('closes network and returns to chat', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');

            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('network-close')));
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('does not show preview column when network view is open', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();

            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));

            // Network is shown, preview column is hidden
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();
            expect(screen.queryByTestId('browser-preview')).not.toBeInTheDocument();
        });

        it('previews return when network view is closed', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });

            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.queryByTestId('browser-preview')).not.toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('network-close')));
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();
        });
    });

    // ── Detail view (agent selected) ────────────────────────────────

    describe('detail view', () => {
        it('shows activity view when agent is selected from network view', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');

            // Open network first, then select an agent through the feature UI.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));

            expect(screen.getByTestId('agent-activity-view')).toBeInTheDocument();
        });

        it('returns to network view from agent activity', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');

            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            expect(screen.getByTestId('agent-activity-view')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('activity-back')));
            expect(screen.queryByTestId('agent-activity-view')).not.toBeInTheDocument();
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();
        });
    });

    // ── Escaping full-view panels (settings / routines) ────────────────
    // Regression: starting or loading a conversation from a full-view
    // panel left the user stuck because the chat column stayed hidden
    // behind settings/routines.

    describe('escaping settings / routines via conversation actions', () => {
        it('new chat closes the settings page and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.queryByTestId('settings-page')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('new chat closes the routines view and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.queryByTestId('routines-view')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('opens the agents view from the nav and escapes it on new chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-agents')));
            expect(screen.getByTestId('agents-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.queryByTestId('agents-view')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('loading a conversation closes the settings page and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expect(screen.queryByTestId('settings-page')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('loading a conversation closes the routines view and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expect(screen.queryByTestId('routines-view')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('clicking the already-active conversation returns to chat WITHOUT re-resuming', async () => {
            // Repro: from a sub-agent's activity view, clicking the active
            // conversation in the list should just navigate back — not refetch
            // and RESET it. (load-conversation button loads 'conv-1'.)
            const loadConversation = vi.fn();
            streamMock.value = {
                ...streamMock.makeDefault(),
                loadConversation,
                activeConversationId: 'conv-1',
            };
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expect(screen.queryByTestId('settings-page')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(loadConversation).not.toHaveBeenCalled();
        });

        it('clicking a different conversation does resume it', async () => {
            const loadConversation = vi.fn();
            streamMock.value = {
                ...streamMock.makeDefault(),
                loadConversation,
                activeConversationId: 'a-different-conversation',
            };
            await renderApp();
            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expect(loadConversation).toHaveBeenCalledWith('conv-1');
        });

        it('toggling the active panel off returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('close-panel')));
            expect(screen.queryByTestId('settings-page')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });

        it('switching from settings to routines shows only routines, never both', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();
            expect(screen.queryByTestId('settings-page')).not.toBeInTheDocument();
        });

        it('opening settings from the network view hides the network', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
        });

        it('keeps a running conversation alive when switching to routines', async () => {
            const stopGeneration = vi.fn();
            streamMock.value = {
                ...streamMock.makeDefault(),
                isStreaming: true,
                // Events-first chat renders from `turns` (not `messages`),
                // which is what Desktop passes to ChatPanel.
                turns: [{ id: 't1' }, { id: 't2' }],
                stopGeneration,
            };
            await renderApp();

            // Chat is showing the in-progress conversation.
            expect(screen.getByTestId('chat-messages')).toHaveTextContent('2 messages');
            expect(screen.getByTestId('chat-streaming')).toHaveTextContent('streaming');

            // Switch to routines mid-stream.
            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();

            // The stream was never told to stop, and the chat stays mounted
            // (hidden, not destroyed) so it keeps running in the background.
            expect(stopGeneration).not.toHaveBeenCalled();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('chat-streaming')).toHaveTextContent('streaming');

            // Back to chat — same conversation, still streaming.
            act(() => fireEvent.click(screen.getByTestId('close-panel')));
            expect(screen.getByTestId('chat-messages')).toHaveTextContent('2 messages');
            expect(screen.getByTestId('chat-streaming')).toHaveTextContent('streaming');
        });

        it('new chat from the network view returns to chat', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
        });
    });

    // ── Preview follows the active view, not a stale selection ──────

    describe('preview content follows the active view', () => {
        it('shows the selected agent preview in its detail view, root preview in chat', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://root.com', title: 'Root', screenshot: TINY_PNG, tabId: 1 },
            });
            startSubAgent(dispatch, 's1', 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 's1',
                snapshot: { url: 'https://sub.com', title: 'Sub', screenshot: TINY_PNG, tabId: 1 },
            });

            // Chat view tracks the root conversation.
            expect(screen.getByText('Browser: https://root.com')).toBeInTheDocument();

            // Drill into the sub-agent — preview follows it.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            expect(screen.getByText('Browser: https://sub.com')).toBeInTheDocument();
        });

        it('does not bleed a stale selection into the chat preview', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://root.com', title: 'Root', screenshot: TINY_PNG, tabId: 1 },
            });
            startSubAgent(dispatch, 's1', 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 's1',
                snapshot: { url: 'https://sub.com', title: 'Sub', screenshot: TINY_PNG, tabId: 1 },
            });

            // Drill into the sub-agent, then bounce out to settings and back.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            expect(screen.getByText('Browser: https://sub.com')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            act(() => fireEvent.click(screen.getByTestId('close-panel')));

            // Back in chat the selection lingers, but the preview tracks the root.
            expect(screen.getByText('Browser: https://root.com')).toBeInTheDocument();
            expect(screen.queryByText('Browser: https://sub.com')).not.toBeInTheDocument();
        });
    });

    // ── Full lifecycle ──────────────────────────────────────────────

    describe('full lifecycle transitions', () => {
        it('simple chat → preview → open network → detail → back to network → close → chat with previews', async () => {
            const { dispatch } = await renderApp();

            // 1. Start in simple chat
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();

            // 2. Root agent starts, browser snapshot appears → preview column
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();

            // 3. Sub-agent spawns → indicator appears, chat + preview still visible
            startSubAgent(dispatch, 's1', 'r1');
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();
            expect(screen.getByTestId('network-indicator')).toBeInTheDocument();

            // 4. Click indicator → network view (chat + preview hidden)
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();
            expect(screen.queryByTestId('browser-preview')).not.toBeInTheDocument();

            // 5. Select sub-agent → detail view
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            expect(screen.getByTestId('agent-activity-view')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();

            // 6. Back → network
            act(() => fireEvent.click(screen.getByTestId('activity-back')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-activity-view')).not.toBeInTheDocument();

            // 7. Close network → back to chat with previews
            act(() => fireEvent.click(screen.getByTestId('network-close')));
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.getByTestId('browser-preview')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
        });
    });
});
