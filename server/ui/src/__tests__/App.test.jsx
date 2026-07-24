import { render, screen, act, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { AppDataProvider } from '../contexts/AppData.jsx';
import { DESKTOP_WINDOW_STORAGE_KEY } from '../features/desktop/desktopWindowPersistence.js';

// Minimal 1x1 transparent PNG
const TINY_PNG = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAADElEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg==';

// ── Mock heavy child components ─────────────────────────────────────
// We only care about which panels / views are mounted, not their internals.

vi.mock('../components/ChatPanel.jsx', () => ({
    default: ({ turns, isStreaming, networkAgentCount, onOpenNetwork, draft }) => (
        <div data-testid="chat-panel">
            Chat
            <span data-testid="chat-messages">{turns?.length || 0} messages</span>
            <span data-testid="chat-streaming">{isStreaming ? 'streaming' : 'idle'}</span>
            <span data-testid="chat-draft">{draft}</span>
            {networkAgentCount > 0 && (
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

vi.mock('../features/agent/AgentNetworkView.jsx', () => ({
    default: ({
        selectedAgentId,
        onClose,
        onOpenOverview,
        onSelectAgent,
        onOpenExecutionView,
    }) => selectedAgentId ? (
        <div data-testid="agent-activity-view">
            Activity View
            <button data-testid="activity-back" onClick={onOpenOverview}>Back</button>
            <button
                data-testid="activity-open-browser"
                onClick={() => onOpenExecutionView(selectedAgentId, 'browser')}
            >
                Browser
            </button>
            <button
                data-testid="activity-open-terminal"
                onClick={() => onOpenExecutionView(selectedAgentId, 'terminal')}
            >
                Terminal
            </button>
        </div>
    ) : (
        <div data-testid="agent-network">
            Network Graph
            <button data-testid="network-select-agent" onClick={() => onSelectAgent('s1')}>Select</button>
            <button data-testid="network-close" onClick={onClose}>Close</button>
        </div>
    ),
}));

vi.mock('../components/Sidebar.jsx', async () => {
    const {
        useDesktopNavigationCommands,
        useDesktopNavigationState,
    } = await import('../features/navigation/DesktopNavigation.jsx');
    return {
        default: ({ onNewConversation, onLoadConversation }) => {
            const { destination } = useDesktopNavigationState();
            const navigation = useDesktopNavigationCommands();
            const activeItem = [
                'settings',
                'routines',
                'agents',
                'artifacts',
                'apps',
            ].includes(destination.kind)
                ? destination.kind
                : 'chat';
            return (
                <div data-testid="sidebar">
                    <span data-testid="sidebar-active-panel">{activeItem}</span>
                    Sidebar
                    <button data-testid="open-settings" onClick={() => navigation.openSettings()}>Settings</button>
                    <button data-testid="open-routines" onClick={() => navigation.openRoutines()}>Routines</button>
                    <button data-testid="open-agents" onClick={() => navigation.openAgents()}>Agents</button>
                    <button data-testid="open-apps" onClick={() => navigation.openApps()}>Apps</button>
                    <button data-testid="close-panel" onClick={() => navigation.openChat()}>Close panel</button>
                    <button data-testid="new-chat" onClick={onNewConversation}>New chat</button>
                    <button data-testid="load-conversation" onClick={() => onLoadConversation('conv-1')}>Load</button>
                </div>
            );
        },
    };
});

vi.mock('../components/SplitHandle.jsx', () => ({
    default: () => <div data-testid="split-handle" />,
}));

vi.mock('../components/FilePreview.jsx', () => ({
    default: ({ item }) => (
        <div data-testid="file-preview-inline">{item?.filename}</div>
    ),
}));

vi.mock('../components/SettingsPage.jsx', () => ({
    default: () => <div data-testid="settings-page">Settings</div>,
}));

vi.mock('../components/apps/AppsView.jsx', () => ({
    default: ({ onOpenApp }) => (
        <div data-testid="apps-view">
            Apps
            <button data-testid="mock-open-app-full" onClick={() => onOpenApp({
                slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts',
            })}>Open full</button>
            <button data-testid="mock-open-notes" onClick={() => onOpenApp({
                slug: 'notes-lab', title: 'Notes Lab', icon: 'bi-journal',
            })}>Open Notes</button>
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
        activeConversationId: 'conversation-1',
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
let capturedAppEffectDispatch = null;

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

vi.mock('../features/app/AppEffects.jsx', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useAppEffectDispatch: () => {
            const dispatch = actual.useAppEffectDispatch();
            capturedAppEffectDispatch = dispatch;
            return dispatch;
        },
    };
});

async function renderApp() {
    capturedDispatch = null;
    capturedWorkspaceDispatch = null;
    capturedAppEffectDispatch = null;
    let rootAgentId = null;
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
            if (action.type === 'AGENT_STARTED' && !action.parentAgentId) {
                rootAgentId = action.agentId;
            }
            const workspaceAction = action.type === 'AGENT_STARTED'
                ? {
                    type: 'WORKSPACE_AGENT_STARTED',
                    agentId: action.agentId,
                    parentAgentId: action.parentAgentId,
                }
                : action;
            capturedWorkspaceDispatch(workspaceAction);
            if (
                action.agentId === rootAgentId
                && ['UPDATE_BROWSER_SNAPSHOT', 'UPDATE_TERMINAL'].includes(action.type)
            ) {
                capturedAppEffectDispatch({
                    type: 'conversation-execution/root-view-available',
                    conversationId: streamMock.value.activeConversationId,
                    agentId: action.agentId,
                    agentName: 'omnideck',
                    resourceId: action.type === 'UPDATE_BROWSER_SNAPSHOT'
                        ? 'browser'
                        : 'terminal',
                });
            }
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

function surfaceHostFor(testId) {
    return screen.getByTestId(testId).closest('[data-surface-id]');
}

function expectSurfaceActive(testId, paneId = null) {
    const host = surfaceHostFor(testId);
    expect(host).toHaveAttribute('data-active', 'true');
    if (paneId) expect(host).toHaveAttribute('data-pane-id', paneId);
    return host;
}

function expectSurfaceInactive(testId) {
    const host = surfaceHostFor(testId);
    expect(host).toHaveAttribute('data-active', 'false');
    return host;
}

// ─────────────────────────────────────────────────────────────────────

describe('App view transitions', () => {
    beforeEach(() => {
        capturedDispatch = null;
        capturedWorkspaceDispatch = null;
        capturedAppEffectDispatch = null;
        streamMock.value = streamMock.makeDefault();
        localStorage.removeItem(DESKTOP_WINDOW_STORAGE_KEY);
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

        it('can reopen the active conversation after its tab is closed', async () => {
            await renderApp();

            fireEvent.click(screen.getByTestId(
                'close-surface-tab-destination:conversation',
            ));
            expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument();

            await act(async () => fireEvent.click(
                screen.getByTestId('load-conversation'),
            ));
            expectSurfaceActive('chat-panel', 'left');
        });

        it('ignores legacy Home metadata and starts on Chat', async () => {
            globalThis.fetch = vi.fn((url) => {
                if (url === '/api/settings') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({ setup_complete: true }),
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
            expectSurfaceActive('chat-panel', 'left');
            expect(screen.queryByTestId('custom-app-frame')).not.toBeInTheDocument();
            expect(screen.queryByTestId('desktop-pane-right')).not.toBeInTheDocument();
        });
    });

    describe('desktop Custom App surfaces', () => {
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
                if (url === '/api/custom-apps') {
                    return Promise.resolve({
                        ok: true,
                        json: () => Promise.resolve({
                            apps: [
                                { slug: 'text-lab', title: 'Text Lab', icon: 'bi-fonts' },
                                { slug: 'notes-lab', title: 'Notes Lab', icon: 'bi-journal' },
                            ],
                        }),
                    });
                }
                if (url.startsWith('/api/models')) {
                    return Promise.resolve({ ok: true, json: () => Promise.resolve({ models: [] }) });
                }
                return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
            });
        });

        it('moves an app between tab stacks, survives New chat, and can close', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));

            const frame = screen.getByTestId('custom-app-frame');
            const leftHost = expectSurfaceActive('custom-app-frame', 'left');
            expect(screen.queryByTestId('desktop-pane-right')).not.toBeInTheDocument();

            fireEvent.click(screen.getByTestId(
                'move-surface-custom-app:text-lab-right',
            ));
            const rightHost = expectSurfaceActive('custom-app-frame', 'right');
            expect(rightHost).toBe(leftHost);
            expect(screen.getByTestId('custom-app-frame')).toBe(frame);
            expectSurfaceActive('apps-view', 'left');
            expect(screen.getByTestId('desktop-window-layout')).toHaveAttribute('data-split', 'true');

            fireEvent.click(screen.getByTestId(
                'maximize-surface-custom-app:text-lab',
            ));
            expect(rightHost).toHaveAttribute('data-maximized', 'true');
            expect(screen.getByTestId('custom-app-frame')).toBe(frame);
            fireEvent.click(screen.getByTestId(
                'restore-surface-custom-app:text-lab',
            ));
            expect(rightHost).toHaveAttribute('data-maximized', 'false');

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expectSurfaceActive('custom-app-frame', 'right');

            fireEvent.click(screen.getByTestId('close-surface-tab-custom-app:text-lab'));
            expect(screen.queryByTestId('desktop-pane-right')).not.toBeInTheDocument();
            expectSurfaceActive('chat-panel', 'left');
        });

        it('opens the current chat and seeds its composer from explicit app context', async () => {
            const setDraft = vi.fn();
            streamMock.value = { ...streamMock.makeDefault(), draft: '', setDraft };
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId('mock-workspace-compose'));

            expectSurfaceInactive('custom-app-frame');
            expectSurfaceActive('chat-panel', 'left');
            expect(screen.queryByTestId('desktop-pane-right')).not.toBeInTheDocument();
            expect(setDraft).toHaveBeenCalledOnce();
            const updateDraft = setDraft.mock.calls[0][0];
            expect(updateDraft('Existing draft')).toContain('Context from Text Lab');
            expect(updateDraft('')).toContain('"Draft"');
        });

        it('moves an app from the right pane back to the left pane', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId(
                'move-surface-custom-app:text-lab-right',
            ));

            const frame = screen.getByTestId('custom-app-frame');
            const rightHost = expectSurfaceActive('custom-app-frame', 'right');
            fireEvent.click(screen.getByTestId(
                'move-surface-custom-app:text-lab-left',
            ));
            const leftHost = expectSurfaceActive('custom-app-frame', 'left');
            expect(leftHost).toBe(rightHost);
            expect(screen.getByTestId('custom-app-frame')).toBe(frame);
            expect(screen.queryByTestId('desktop-pane-right')).not.toBeInTheDocument();

            fireEvent.click(screen.getByTestId(
                'close-surface-tab-custom-app:text-lab',
            ));
            expect(screen.queryByTestId('custom-app-frame')).not.toBeInTheDocument();
            expectSurfaceActive('apps-view', 'left');
        });

        it('keeps the Custom App mounted while another tab is selected', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));

            const frame = screen.getByTestId('custom-app-frame');
            await act(async () => {
                fireEvent.click(screen.getByTestId('open-settings'));
            });
            expectSurfaceActive('settings-page', 'left');
            expectSurfaceInactive('custom-app-frame');
            expect(frame).toBeInTheDocument();
            expect(frame).toHaveAttribute('data-active', 'false');

            fireEvent.click(screen.getByTestId('surface-tab-custom-app:text-lab'));
            expectSurfaceActive('custom-app-frame', 'left');
            expect(screen.getByTestId('custom-app-frame')).toBe(frame);
        });

        it('restores open tabs, pane placement, and active selections after remount', async () => {
            const loadConversation = vi.fn(() => true);
            streamMock.value = { ...streamMock.makeDefault(), loadConversation };
            const firstRender = await renderApp();

            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId(
                'move-surface-custom-app:text-lab-right',
            ));
            await act(async () => {
                fireEvent.click(screen.getByTestId('open-settings'));
            });

            expectSurfaceActive('settings-page', 'left');
            expectSurfaceActive('custom-app-frame', 'right');
            expect(
                JSON.parse(localStorage.getItem(DESKTOP_WINDOW_STORAGE_KEY))
                    .window.panes.left.activeSurfaceId,
            ).toBe('destination:settings');
            firstRender.unmount();

            await renderApp();

            expect(loadConversation).toHaveBeenCalledWith('conversation-1');
            expect(screen.getByTestId(
                'surface-tab-destination:conversation',
            )).toBeInTheDocument();
            expect(screen.getByTestId(
                'surface-tab-destination:apps',
            )).toBeInTheDocument();
            expectSurfaceActive('settings-page', 'left');
            expectSurfaceActive('custom-app-frame', 'right');
        });

        it('keeps a right-pane Custom App in place when loading a conversation', async () => {
            const loadConversation = vi.fn(() => true);
            streamMock.value = { ...streamMock.makeDefault(), loadConversation };
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId(
                'move-surface-custom-app:text-lab-right',
            ));

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));

            expect(loadConversation).toHaveBeenCalledWith('conv-1');
            expectSurfaceActive('custom-app-frame', 'right');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('does not leave Apps highlighted after entering an app workspace', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('apps');

            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('chat');

            expect(screen.getByTestId('sidebar-active-panel')).toHaveTextContent('chat');
        });

        it('keeps multiple Custom Apps mounted as independent tabs', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId('open-apps'));
            fireEvent.click(screen.getByTestId('mock-open-notes'));

            expect(screen.getByTestId(
                'surface-tab-custom-app:text-lab',
            )).toBeInTheDocument();
            expect(screen.getByTestId(
                'surface-tab-custom-app:notes-lab',
            )).toBeInTheDocument();
            expect(screen.getAllByTestId('custom-app-frame')).toHaveLength(2);

            const textSurface = screen.getByTestId(
                'desktop-surface-custom-app:text-lab',
            );
            const notesSurface = screen.getByTestId(
                'desktop-surface-custom-app:notes-lab',
            );
            expect(textSurface).toHaveAttribute('data-active', 'false');
            expect(notesSurface).toHaveAttribute('data-active', 'true');
        });

        it('applies tab context-menu close commands without first selecting the tab', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-apps')));
            fireEvent.click(await screen.findByTestId('mock-open-app-full'));
            fireEvent.click(screen.getByTestId('open-apps'));
            fireEvent.click(screen.getByTestId('mock-open-notes'));

            const textTab = screen.getByTestId(
                'surface-tab-custom-app:text-lab',
            );
            expect(screen.getByTestId(
                'desktop-surface-custom-app:text-lab',
            )).toHaveAttribute('data-active', 'false');

            fireEvent.contextMenu(textTab);
            fireEvent.click(screen.getByRole(
                'menuitem',
                { name: 'Close tabs to the right' },
            ));

            expect(screen.queryByTestId(
                'desktop-surface-custom-app:notes-lab',
            )).not.toBeInTheDocument();
            expectSurfaceActive('custom-app-frame', 'left');

            fireEvent.contextMenu(textTab);
            fireEvent.click(screen.getByRole(
                'menuitem',
                { name: 'Close other tabs' },
            ));

            expect(screen.getByTestId(
                'surface-tab-custom-app:text-lab',
            )).toBeInTheDocument();
            expect(screen.queryByTestId(
                'surface-tab-destination:conversation',
            )).not.toBeInTheDocument();
            expect(screen.queryByTestId(
                'surface-tab-destination:apps',
            )).not.toBeInTheDocument();
        });
    });

    // ── Conversation execution tabs ─────────────────────────────────

    describe('conversation execution tabs', () => {
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

        it('moves an execution tab between the same left and right pane stacks', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: {
                    url: 'https://test.com',
                    title: 'Test',
                    screenshot: TINY_PNG,
                    tabId: 1,
                },
            });

            const browser = screen.getByTestId('browser-preview');
            const surfaceHost = expectSurfaceActive('browser-preview', 'right');
            fireEvent.click(screen.getByTestId('move-surface-browser-left'));
            expectSurfaceActive('browser-preview', 'left');
            expect(surfaceHostFor('browser-preview')).toBe(surfaceHost);
            expect(screen.getByTestId('browser-preview')).toBe(browser);
            expectSurfaceInactive('chat-panel');

            fireEvent.click(screen.getByTestId('move-surface-browser-right'));
            expectSurfaceActive('browser-preview', 'right');
            expectSurfaceActive('chat-panel', 'left');
            expect(surfaceHostFor('browser-preview')).toBe(surfaceHost);
            expect(screen.getByTestId('browser-preview')).toBe(browser);
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

        it('ignores retired generation preview events', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_GENERATION_PREVIEW',
                agentId: 'r1',
                preview: { gen_id: 'g1', media_type: 'image', status: 'generating', step: 5, total_steps: 20 },
            });

            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.queryByTestId('generation-preview')).not.toBeInTheDocument();
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

        it('closes execution tabs with Chat and does not reopen them with the conversation', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: {
                    url: 'https://test.com',
                    title: 'Test',
                    screenshot: TINY_PNG,
                    tabId: 1,
                },
            });

            fireEvent.click(screen.getByTestId(
                'close-surface-tab-destination:conversation',
            ));
            expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument();
            expect(screen.queryByTestId('browser-preview')).not.toBeInTheDocument();

            await act(async () => fireEvent.click(
                screen.getByTestId('load-conversation'),
            ));
            expectSurfaceActive('chat-panel', 'left');
            expect(screen.queryByTestId('browser-preview')).not.toBeInTheDocument();
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
            expectSurfaceActive('chat-panel', 'left');
        });

        it('keeps an independent execution tab open when network view is selected', async () => {
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

            expectSurfaceActive('agent-network', 'left');
            expectSurfaceActive('browser-preview', 'right');
        });

        it('keeps the execution tab active when network view is closed', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            dispatch({
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'r1',
                snapshot: { url: 'https://test.com', title: 'Test', screenshot: TINY_PNG, tabId: 1 },
            });

            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expectSurfaceActive('browser-preview', 'right');

            act(() => fireEvent.click(screen.getByTestId('network-close')));
            expectSurfaceActive('browser-preview', 'right');
            expectSurfaceActive('chat-panel', 'left');
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
            expectSurfaceInactive('settings-page');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('new chat closes the routines view and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expectSurfaceInactive('routines-view');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('opens the agents view from the nav and escapes it on new chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-agents')));
            expect(screen.getByTestId('agents-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('new-chat')));
            expectSurfaceInactive('agents-view');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('loading a conversation closes the settings page and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expectSurfaceInactive('settings-page');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('loading a conversation closes the routines view and returns to chat', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expect(screen.getByTestId('routines-view')).toBeInTheDocument();

            await act(async () => fireEvent.click(screen.getByTestId('load-conversation')));
            expectSurfaceInactive('routines-view');
            expectSurfaceActive('chat-panel', 'left');
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
            expectSurfaceInactive('settings-page');
            expectSurfaceActive('chat-panel', 'left');
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
            expectSurfaceInactive('settings-page');
            expectSurfaceActive('chat-panel', 'left');
        });

        it('switching from settings to routines selects routines while retaining both tabs', async () => {
            await renderApp();
            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expect(screen.getByTestId('settings-page')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('open-routines')));
            expectSurfaceActive('routines-view', 'left');
            expectSurfaceInactive('settings-page');
        });

        it('opening settings from the network view hides the network', async () => {
            const { dispatch } = await renderApp();
            startRoot(dispatch, 'r1');
            startSubAgent(dispatch, 's1', 'r1');
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expect(screen.getByTestId('agent-network')).toBeInTheDocument();

            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            expectSurfaceActive('settings-page', 'left');
            expectSurfaceInactive('agent-network');
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
            expectSurfaceActive('chat-panel', 'left');
        });
    });

    // ── Agent-attributed execution tabs ─────────────────────────────

    describe('agent-attributed execution tabs', () => {
        it('keeps the root Browser open until the user opens the sub-agent Browser', async () => {
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

            // Selecting the sub-agent does not replace or focus its Browser.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            expect(screen.queryByTestId('desktop-surface-s1:browser'))
                .not.toBeInTheDocument();
            expectSurfaceActive('browser-preview', 'right');

            // The explicit action opens a distinct, agent-bound tab.
            act(() => fireEvent.click(screen.getByTestId('activity-open-browser')));
            const subAgentBrowser = screen.getByTestId(
                'desktop-surface-s1:browser',
            );
            expect(subAgentBrowser).toHaveAttribute('data-active', 'true');
            expect(subAgentBrowser).toHaveAttribute('data-surface-owner-id', 's1');
            expect(subAgentBrowser).toHaveTextContent('Browser: https://sub.com');
            expect(screen.getByTestId('desktop-surface-browser'))
                .toHaveAttribute('data-active', 'false');
        });

        it('does not change an explicitly opened sub-agent tab when navigating elsewhere', async () => {
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

            // Explicitly open the sub-agent Browser, then navigate elsewhere.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            act(() => fireEvent.click(screen.getByTestId('network-select-agent')));
            act(() => fireEvent.click(screen.getByTestId('activity-open-browser')));
            expect(screen.getByTestId('desktop-surface-s1:browser'))
                .toHaveAttribute('data-active', 'true');

            act(() => fireEvent.click(screen.getByTestId('open-settings')));
            act(() => fireEvent.click(screen.getByTestId('close-panel')));

            expectSurfaceActive('chat-panel', 'left');
            expect(screen.getByTestId('desktop-surface-s1:browser'))
                .toHaveAttribute('data-active', 'true');
            expect(screen.getByTestId('desktop-surface-s1:browser'))
                .toHaveTextContent('Browser: https://sub.com');
        });
    });

    // ── Full lifecycle ──────────────────────────────────────────────

    describe('full lifecycle transitions', () => {
        it('simple chat → preview → open network → detail → back to network → close → chat with previews', async () => {
            const { dispatch } = await renderApp();

            // 1. Start in simple chat
            expect(screen.getByTestId('chat-panel')).toBeInTheDocument();
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();

            // 2. Root agent starts, browser snapshot appears → right Browser tab
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

            // 4. Click indicator → network on the left; Browser remains on the right.
            act(() => fireEvent.click(screen.getByTestId('network-indicator')));
            expectSurfaceActive('agent-network', 'left');
            expectSurfaceActive('browser-preview', 'right');

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
            expectSurfaceActive('chat-panel', 'left');
            expectSurfaceActive('browser-preview', 'right');
            expect(screen.queryByTestId('agent-network')).not.toBeInTheDocument();
        });
    });
});
