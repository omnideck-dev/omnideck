import { useState, useEffect, useRef, useCallback, useMemo } from 'react';

import ChatPanel from './components/ChatPanel.jsx';
import BrowserPreview from './components/BrowserPreview.jsx';
import DesktopPreview from './components/DesktopPreview.jsx';
import SettingsPage from './components/SettingsPage.jsx';
import SetupWizard from './components/SetupWizard.jsx';
import { useAppData } from './contexts/AppData.jsx';
import { ConversationsProvider, useConversations } from './contexts/Conversations.jsx';
import TerminalPanel from './components/TerminalOutput.jsx';
import GenerationPreview from './components/GenerationPreview.jsx';
import AgentNetwork from './components/AgentNetwork.jsx';
import AgentActivityView from './components/AgentActivityView.jsx';
import Sidebar from './components/Sidebar.jsx';
import RoutinesView from './components/routines/RoutinesView.jsx';
import AgentsView from './components/agents/AgentsView.jsx';
import ArtifactsHubView from './components/artifacts/ArtifactsHubView.jsx';
import AppsView from './components/apps/AppsView.jsx';
import HomeView from './components/apps/HomeView.jsx';
import CustomAppWorkspace from './components/apps/CustomAppWorkspace.jsx';
import PreviewPanel from './components/PreviewPanel.jsx';
import SplitHandle from './components/SplitHandle.jsx';
import FilePreview from './components/FilePreview.jsx';
import BrowserFullscreen from './components/BrowserFullscreen.jsx';
import useBrowserTabs from './hooks/useBrowserTabs.js';
// useModelSettings removed — replaced by profile-based configuration
import useStreamingChat from './hooks/useStreamingChat.js';
import { replayEventsToAgentState } from './hooks/_replayEvents.js';
import usePreviewState from './hooks/usePreviewState.jsx';
import { AgentStateProvider, useAgentState, useAgentDispatch } from './hooks/useAgentState.jsx';
import { useToast } from './components/ToastProvider.jsx';
import styles from './App.module.css';

/**
 * Main app shell. Preview data (browser screenshots, terminal output, etc.)
 * lives in the agent reducer — one source of truth for all views. The
 * simple chat preview column reads from the root agent's node, same as
 * the agent detail view reads from any selected agent's node.
 */
function DesktopAppInner() {
    const agentDispatch = useAgentDispatch();
    const agentState = useAgentState();

    // ── UI-only state (not duplicated in the reducer) ───────────────
    const [attachment, setAttachment] = useState(null);
    // The single top-level view. Mutually exclusive by construction, so a new
    // chat or panel switch can't leave a stale view stacked underneath. Agent
    // detail is a sub-state of 'network', keyed off selectedAgentId in the
    // agent reducer — not a separate value here.
    const [view, setView] = useState('chat'); // 'chat' | full-screen panel | 'network'
    const [memoryRefreshSignal, setMemoryRefreshSignal] = useState(0);
    const [toolsRefreshSignal, setToolsRefreshSignal] = useState(0);
    const [pendingAudio, setPendingAudio] = useState(null);
    const [muted, setMuted] = useState(false);
    const [userDesktopOpen, setUserDesktopOpen] = useState(false);
    const [homeAppSlug, setHomeAppSlug] = useState(null);
    const [workspaceApp, setWorkspaceApp] = useState(null);
    const [workspaceLayout, setWorkspaceLayout] = useState('full');
    const [workspaceOrigin, setWorkspaceOrigin] = useState('apps');
    const [workspaceActiveTab, setWorkspaceActiveTab] = useState(null);
    const initialHomeAppliedRef = useRef(false);
    const { profilesHook, features } = useAppData();
    const { addStartedConversation, focusFileInConversation } = useConversations();

    // Agent profile is per chat session, not global. `convProfile` is the
    // profile chosen for the conversation currently in view; null means "use
    // the system default", so a new chat never inherits the previously viewed
    // chat's profile. The conversation's profile is the backend's to own —
    // it's saved on each turn and handed back on resume, so this only holds
    // the in-view selection, not a cache of every session.
    const [convProfile, setConvProfile] = useState(null);
    // The system default profile comes from settings (`default_agent`), loaded
    // below. The chat never renders until that fetch resolves (gated on
    // setupComplete), so this is populated before any profile is read — no
    // hardcoded fallback to drift out of sync with the actual default.
    const [defaultProfileId, setDefaultProfileId] = useState(null);

    // Setup wizard state
    const [setupComplete, setSetupComplete] = useState(null); // null = loading

    useEffect(() => {
        fetch('/api/settings').then(r => r.json()).then(data => {
            setSetupComplete(data.setup_complete || false);
            if (data.default_agent) setDefaultProfileId(data.default_agent);
            if (data.home_app_slug) setHomeAppSlug(data.home_app_slug);
        }).catch(() => setSetupComplete(false));
    }, []);

    useEffect(() => {
        if (initialHomeAppliedRef.current || setupComplete !== true) return;
        if (!features.custom_apps || !homeAppSlug) return;
        initialHomeAppliedRef.current = true;
        setView('home');
    }, [features.custom_apps, homeAppSlug, setupComplete]);

    useEffect(() => {
        if (features.custom_apps) return;
        setWorkspaceApp(null);
        setWorkspaceActiveTab(null);
        setWorkspaceOrigin('apps');
        setView((current) => ['apps', 'home', 'workspace'].includes(current) ? 'chat' : current);
    }, [features.custom_apps]);

    const { addToast } = useToast();

    // Preview follows the selected agent only while its detail view is up
    // (network view); in chat/settings/routines it tracks the root conversation.
    const preview = usePreviewState(view === 'network');

    // Holds the active-tab id the resume callback wants to apply once
    // usePreviewState has the new root in scope. Synced in an effect below.
    const _pendingActiveTabRef = useRef(null);

    // ── Stream callbacks ──────────────────────────────────────────────
    // Called by useStreamingChat when events arrive from the backend.
    // Preview events dispatch once to the agent reducer — no dual state.
    //
    // Created once via useRef — the streaming hook keeps a stable reference
    // and doesn't restart on re-render. All callbacks use dispatch/setState
    // updaters which are stable across renders. Do NOT read state variables
    // directly in these callbacks — they would capture a stale closure.
    const _callbacks = useRef({
        onBrowserSnapshot: (snapshot) => {
            agentDispatch({ type: 'UPDATE_BROWSER_SNAPSHOT', agentId: snapshot.agentId, snapshot });
        },
        onTerminalOutput: (event) => {
            agentDispatch({ type: 'UPDATE_TERMINAL', agentId: event.agentId, event });
        },
        onToolCreated: () => setToolsRefreshSignal((s) => s + 1),
        onMemoryChanged: () => setMemoryRefreshSignal((s) => s + 1),
        onAudioPlayback: (audio) => setPendingAudio(audio),
        onNudgeSent: (result) => {
            if (result.ok) {
                addToast('Nudge sent', { type: 'info', duration: 3000 });
            } else if (result.status === 409) {
                addToast('Agent is no longer running', { type: 'warn', duration: 5000 });
            } else {
                addToast(result.error || 'Could not send nudge', { type: 'error' });
            }
        },
        onDesktopActive: (agentId) => {
            agentDispatch({ type: 'UPDATE_DESKTOP_ACTIVE', agentId });
        },
        onGenerationPreview: (event) => {
            agentDispatch({ type: 'UPDATE_GENERATION_PREVIEW', agentId: event.agentId, preview: event });
        },
        // When an agent starts or finishes, add/update it in the tree.
        onAgentEvent: (event) => {
            if (event.type === 'agent_started') {
                agentDispatch({
                    type: 'AGENT_STARTED',
                    agentId: event.agent_id,
                    agentName: event.agent_name,
                    parentAgentId: event.parent_agent_id || null,
                    instruction: event.instruction,
                    correlationId: event.correlation_id || null,
                    timestamp: Date.now(),
                });
            } else if (event.type === 'agent_completed') {
                agentDispatch({
                    type: 'AGENT_COMPLETED',
                    agentId: event.agent_id,
                    status: event.status,
                });
            }
        },
        // Sub-agent text tokens, batched ~60x/sec. We merge content and
        // thinking in one update so they don't get jumbled together.
        onAgentContent: ({ agentId, content, thinking }) => {
            agentDispatch({
                type: 'APPEND_STREAM_CHUNK',
                agentId,
                content: content || null,
                thinking: thinking || null,
            });
        },
        // Agent context usage (iteration + context window fill)
        onAgentContextUsage: ({ agentId, iteration, maxIterations, contextUsage }) => {
            agentDispatch({ type: 'UPDATE_ITERATION', agentId, iteration, maxIterations, contextUsage });
        },
        // Agent file output — activity log entry is buffered by
        // useStreamingChat, this callback handles any side effects.
        onAgentFileOutput: () => {},
        // Buffered activity log entry (tool call, file output) — dispatched
        // by useStreamingChat in correct chronological order.
        onActivityEntry: ({ agentId, entry }) => {
            agentDispatch({ type: 'APPEND_ACTIVITY', agentId, entry });
        },
        // A previously-saved conversation just finished loading. Replay
        // the persisted events through useAgentState so the network
        // view, per-agent activity logs, and preview panels all match
        // what live SSE would have produced. React 18 batches all
        // dispatches within this async callback into one render.
        onConversationLoaded: ({ events, browserTabs, terminal, previewState, profileId }) => {
            // Restore the profile this conversation was last using so the
            // selector and outgoing requests reflect it. Null falls back to the
            // default — covers conversations saved before profiles were tracked.
            setConvProfile(profileId || null);
            agentDispatch({ type: 'RESET' });
            replayEventsToAgentState(events, agentDispatch);

            // Panel state restores from the bounded sidecars — screenshots
            // and terminal transcripts aren't in the event log.
            for (const tab of (browserTabs || [])) {
                if (!tab?.agent_id) continue;
                agentDispatch({
                    type: 'UPDATE_BROWSER_SNAPSHOT',
                    agentId: tab.agent_id,
                    snapshot: {
                        url: tab.url,
                        title: tab.title,
                        screenshot: tab.screenshot,
                        tabId: tab.tab_id ?? null,
                        agentId: tab.agent_id,
                    },
                });
            }
            for (const [termAgentId, entries] of Object.entries(terminal || {})) {
                for (const entry of (entries || [])) {
                    agentDispatch({
                        type: 'UPDATE_TERMINAL',
                        agentId: termAgentId,
                        event: entry,
                    });
                }
            }

            // The latest root agent's id is where re-opened preview tabs
            // (saved by the user before the page reload) need to land,
            // so the per-turn carry-over keeps them visible on the next
            // live turn.
            let lastRootAgentId = null;
            for (const ev of events) {
                if (ev?.type === 'agent_started' && !ev.parent_agent_id) {
                    lastRootAgentId = ev.agent_id;
                }
            }
            if (!lastRootAgentId) {
                _pendingActiveTabRef.current = null;
                return;
            }

            // Restore the open tabs straight from the saved paths — independent
            // of the event log, so a file opened from another conversation (or
            // one whose file_output isn't in this conversation's replay) still
            // reopens. Rendering keys off the filename extension downstream.
            const openPaths = Array.isArray(previewState?.open_files)
                ? previewState.open_files
                : [];
            for (const path of openPaths) {
                if (typeof path !== 'string' || !path) continue;
                const item = { type: 'file_output', filename: path.split('/').pop() || path, path };
                agentDispatch({ type: 'OPEN_FILE', agentId: lastRootAgentId, item });
            }

            _pendingActiveTabRef.current = typeof previewState?.active_tab === 'string'
                ? previewState.active_tab
                : null;
        },
        // A brand-new conversation just started its first turn — let the
        // conversations store add the row and generate its title.
        onConversationStarted: addStartedConversation,
    }).current;

    const {
        turns,
        stalled,
        isStreaming,
        stopRequested,
        sendMessage,
        sendNudge,
        stopGeneration,
        loadConversation,
        newConversation: chatNewConversation,
        activeConversationId,
        draft,
        setDraft,
        savePreviewState,
    } = useStreamingChat(_callbacks);

    // The browser side channel + tab model, shared by the inline and fullscreen
    // views. Control (input) is only allowed while no turn is active.
    const browser = useBrowserTabs({
        conversationId: activeConversationId,
        canControl: !isStreaming,
        enabled: preview.browserTabsList.length > 0
            && (preview.activeTab === 'browser' || preview.fullscreenItem?.kind === 'browser'),
        agentTabs: preview.browserTabsList,
    });

    // The profile for the open conversation: its own pick, or the default.
    const selectedProfileId = convProfile ?? defaultProfileId;
    const handleProfileChange = useCallback((id) => setConvProfile(id), []);

    // After a resume, apply the pending active-tab once the preview hook
    // re-renders with the new root agent and its restored files.
    useEffect(() => {
        if (_pendingActiveTabRef.current === null) return;
        const target = _pendingActiveTabRef.current;
        if (preview.tabs.some((t) => t.id === target)) {
            preview.setActiveTab(target);
            _pendingActiveTabRef.current = null;
        }
    }, [preview.tabs, preview.setActiveTab]);

    // Debounced persist of the preview-panel state on any tab/active-tab
    // change. The shape mirrors what the backend writes into metadata.json.
    const _previewStateSnapshot = useMemo(() => {
        const hasTab = (id) => preview.tabs.some((t) => t.id === id);
        return {
            open_files: preview.openFiles.map((f) => f.path || f.filename).filter(Boolean),
            active_tab: preview.activeTab,
            browser_visible: hasTab('browser'),
            terminal_visible: hasTab('terminal'),
            desktop_visible: hasTab('desktop'),
            generation_visible: hasTab('generation'),
        };
    }, [preview.tabs, preview.activeTab, preview.openFiles]);

    useEffect(() => {
        // Only persist the root conversation's preview. A sub-agent's preview
        // (shown while its detail view is up) is ephemeral: on reopen you land
        // on the root, so a restored sub-agent file would either reattach to
        // the wrong agent or stay invisible until you navigate back into that
        // sub-agent. Skip the save whenever the preview is following a sub-agent.
        const followingSubAgent = view === 'network'
            && agentState.selectedAgentId
            && agentState.selectedAgentId !== agentState.rootId;
        if (followingSubAgent) return;
        const s = _previewStateSnapshot;
        const empty = !s.open_files.length && !s.active_tab
            && !s.browser_visible && !s.terminal_visible
            && !s.desktop_visible && !s.generation_visible;
        if (empty) return;
        const handle = setTimeout(() => {
            savePreviewState(s);
        }, 500);
        return () => clearTimeout(handle);
    }, [_previewStateSnapshot, savePreviewState, view, agentState.selectedAgentId, agentState.rootId]);

    const handleSend = useCallback((message, attachments) => {
        setAttachment(null);
        if (isStreaming) {
            if (!stopRequested) sendNudge(message);
        } else {
            // The new-conversation case (optimistic sidebar insert + title
            // generation) is handled by the onConversationStarted callback,
            // which sendMessage fires when it starts a fresh conversation.
            sendMessage(message, attachments, selectedProfileId);
        }
    }, [sendMessage, sendNudge, isStreaming, stopRequested, selectedProfileId]);

    const openDesktop = useCallback(async () => {
        if (userDesktopOpen) return;
        try {
            const res = await fetch('/api/desktop/start', { method: 'POST' });
            const data = await res.json();
            if (data.running) {
                setUserDesktopOpen(true);
            } else {
                addToast(data.error || 'Desktop is not available', { type: 'error' });
            }
        } catch {
            addToast('Could not reach the server', { type: 'error' });
        }
    }, [userDesktopOpen, addToast]);

    const newConversation = useCallback(async (opts) => {
        await chatNewConversation(opts);
        preview.reset();
        // A fresh chat starts on the default profile, never the last one viewed.
        setConvProfile(null);
        // Surface the chat — otherwise a panel/network view stays stacked on
        // top and the new conversation is invisible. RESET clears the agent
        // tree and any selection.
        if (workspaceApp) {
            setWorkspaceLayout('split');
            setWorkspaceActiveTab(`app:${workspaceApp.slug}`);
            setView('workspace');
        } else {
            setView('chat');
        }
        agentDispatch({ type: 'RESET' });
    }, [chatNewConversation, preview.reset, agentDispatch, workspaceApp]);

    // Open a fresh chat with the composer pre-seeded (e.g. composing a routine
    // from the routines view). The chat state seeds the draft in the same batch
    // as the new conversation id.
    const composeInNewChat = useCallback((text) => newConversation({ draft: text }), [newConversation]);

    // Loading a conversation has to surface the chat too, same as newConversation.
    const handleLoadConversation = useCallback((conversationId) => {
        if (workspaceApp) {
            setWorkspaceLayout('split');
            setWorkspaceActiveTab(`app:${workspaceApp.slug}`);
            setView('workspace');
        } else {
            setView('chat');
        }
        // Clicking the already-active conversation (e.g. from a sub-agent's
        // activity view) is just navigation back to its chat — don't re-resume
        // it, which would refetch, RESET the agent tree, and clobber any live
        // turn. Just drop the agent selection and show the chat.
        if (conversationId === activeConversationId) {
            agentDispatch({ type: 'SELECT_AGENT', agentId: null });
            return undefined;
        }
        return loadConversation(conversationId);
    }, [loadConversation, activeConversationId, agentDispatch, workspaceApp]);

    // Open an artifact's source conversation with that file focused. Persist the
    // focus into preview_state first, then either open the file immediately (if
    // the conversation is already active) or load it normally — the resume path
    // restores the focused file. Reuses the single conversation opener; adds no
    // second open path.
    const openArtifactInConversation = useCallback(async (artifact) => {
        const { conversation_id: conversationId, path, filename, content_type: contentType } = artifact;
        try {
            await focusFileInConversation(conversationId, path);
        } catch (_) {
            // Best-effort: navigate even if the focus write fails; the file
            // just won't be pre-opened.
        }
        if (conversationId === activeConversationId) {
            if (workspaceApp) {
                setWorkspaceLayout('split');
                setWorkspaceActiveTab(`file:${path}`);
                setView('workspace');
            } else {
                setView('chat');
            }
            preview.openFile({ filename, content_type: contentType, path });
            return;
        }
        handleLoadConversation(conversationId);
    }, [activeConversationId, handleLoadConversation, preview, focusFileInConversation, workspaceApp]);

    // ── Which layout to show ───────────────────────────────────────────
    // `view` picks exactly one shell surface. The workspace surface has its own
    // full/split presentation state while the app iframe stays mounted. Each is a
    // full replacement of the main column, so they're mutually exclusive by
    // construction — no view can stay stacked under another.
    //
    //   chat (default) — chat + preview panels. Always shows the root agent's
    //     conversation. When sub-agents spawn, a network indicator appears so
    //     the user can navigate to the network.
    //   workspace — a full app, or chat + a global app/conversation-preview rail.
    //   settings / routines — full-screen panels opened from the sidebar.
    //   network — full-screen agent graph. Click a card to drill into an
    //     agent's detail view (network + selectedAgentId); close to return
    //     to chat.
    //
    // Agent detail is a sub-state of network, not a fifth value: it's network
    // with a selectedAgentId set in the agent reducer.

    // Compute network-visible agent stats for the indicator badge.
    // Counts all agents in trees that have sub-agents (same as the
    // network view header) so the numbers match when you open it.
    const { networkAgentCount, networkRunningCount } = useMemo(() => {
        const agents = agentState.agents;
        let total = 0, running = 0;
        // Walk each root that has children (same filter as _buildTrees)
        for (const a of Object.values(agents)) {
            if (a.parentId !== null || a.childIds.length === 0) continue;
            // BFS this tree
            const queue = [a.id];
            while (queue.length > 0) {
                const id = queue.shift();
                const node = agents[id];
                if (!node) continue;
                total++;
                if (node.status === 'running') running++;
                for (const childId of node.childIds) queue.push(childId);
            }
        }
        return { networkAgentCount: total, networkRunningCount: running };
    }, [agentState.agents]);

    // Opening the network lands on the graph, so drop any stale selection
    // (it would otherwise reopen straight into an old agent's detail view).
    const handleOpenNetwork = useCallback(() => {
        setView('network');
        agentDispatch({ type: 'SELECT_AGENT', agentId: null });
    }, [agentDispatch]);

    const handleCloseNetwork = useCallback(() => {
        if (workspaceApp) {
            setWorkspaceLayout('split');
            setView('workspace');
        } else {
            setView('chat');
        }
    }, [workspaceApp]);

    // Drill straight into a sub-agent's activity view — e.g. from a
    // SpawnCard row in the chat.
    const handleSelectAgent = useCallback((agentId) => {
        setView('network');
        agentDispatch({ type: 'SELECT_AGENT', agentId });
    }, [agentDispatch]);

    // Sidebar nav (settings/routines). A null panel means toggle back to chat.
    const handlePanelToggle = useCallback((panel) => {
        if (!panel && workspaceApp) {
            setWorkspaceLayout('split');
            setView('workspace');
            return;
        }
        setView(panel || 'chat');
    }, [workspaceApp]);

    const handleHomeAppChange = useCallback((slug) => {
        initialHomeAppliedRef.current = true;
        setHomeAppSlug(slug);
        if (!slug) setWorkspaceOrigin((current) => current === 'home' ? 'apps' : current);
    }, []);

    const openWorkspaceApp = useCallback((app, layout = 'full', origin = 'apps') => {
        setWorkspaceApp(app);
        setWorkspaceLayout(layout);
        setWorkspaceOrigin(origin);
        setWorkspaceActiveTab(`app:${app.slug}`);
        setView('workspace');
    }, []);

    const openAppFull = useCallback((app) => openWorkspaceApp(app, 'full', 'apps'), [openWorkspaceApp]);
    const openAppBesideChat = useCallback((app) => openWorkspaceApp(app, 'split', 'apps'), [openWorkspaceApp]);
    const openHomeWorkspace = useCallback((app) => openWorkspaceApp(app, 'full', 'home'), [openWorkspaceApp]);
    const openAppsLibrary = useCallback(() => setView('apps'), []);

    const openChatBesideApp = useCallback(() => {
        if (!workspaceApp) return;
        setWorkspaceLayout('split');
        setWorkspaceActiveTab(`app:${workspaceApp.slug}`);
        setView('workspace');
    }, [workspaceApp]);

    const composeFromApp = useCallback(({ text, context }) => {
        if (!workspaceApp) return;
        let addition = text.trim();
        if (context !== null && context !== undefined) {
            try {
                const serialized = JSON.stringify(context, null, 2).slice(0, 12000);
                addition += `${addition ? '\n\n' : ''}Context from ${workspaceApp.title}:\n${serialized}`;
            } catch {
                // Ignore context that cannot be serialized; the authored text is still useful.
            }
        }
        if (addition) {
            setDraft((current) => current.trim() ? `${current}\n\n${addition}` : addition);
        }
        openChatBesideApp();
    }, [workspaceApp, setDraft, openChatBesideApp]);

    const closeWorkspaceApp = useCallback(() => {
        setWorkspaceApp(null);
        setWorkspaceActiveTab(null);
        setWorkspaceOrigin('apps');
        setView('chat');
    }, []);

    const appTabId = workspaceApp ? `app:${workspaceApp.slug}` : null;
    const workspaceTabs = useMemo(() => workspaceApp ? [
        {
            id: appTabId,
            testid: appTabId,
            label: workspaceApp.title,
            icon: <i className={`bi ${workspaceApp.icon}`} />,
        },
        ...preview.tabs,
    ] : [], [workspaceApp, appTabId, preview.tabs]);

    useEffect(() => {
        if (!workspaceApp) return;
        if (workspaceActiveTab === appTabId) return;
        if (!preview.tabs.some((tab) => tab.id === workspaceActiveTab)) {
            setWorkspaceActiveTab(appTabId);
        }
    }, [workspaceApp, workspaceActiveTab, appTabId, preview.tabs]);

    const handleWorkspaceTabChange = useCallback((tabId) => {
        setWorkspaceActiveTab(tabId);
        if (tabId !== appTabId) preview.setActiveTab(tabId);
    }, [appTabId, preview.setActiveTab]);

    const handleWorkspaceCloseTab = useCallback((tabId) => {
        if (tabId === appTabId) {
            closeWorkspaceApp();
            return;
        }
        const remaining = preview.tabs.filter((tab) => tab.id !== tabId);
        preview.closeTab(tabId);
        if (workspaceActiveTab === tabId) {
            setWorkspaceActiveTab(remaining.length > 0 ? remaining[remaining.length - 1].id : appTabId);
        }
    }, [appTabId, closeWorkspaceApp, preview.tabs, preview.closeTab, workspaceActiveTab]);

    const openPreviewFromChat = useCallback((item) => {
        preview.openFile(item);
        if (workspaceApp) {
            setWorkspaceLayout('split');
            setWorkspaceActiveTab(`file:${item.path || item.filename}`);
            setView('workspace');
        }
    }, [preview.openFile, workspaceApp]);

    const workspaceVisible = view === 'workspace' && Boolean(workspaceApp);
    const workspaceSplit = workspaceVisible && workspaceLayout === 'split';
    const activeSidebarPanel = view === 'workspace'
        ? (workspaceLayout === 'full' && workspaceOrigin === 'home' ? 'home' : null)
        : (['settings', 'routines', 'artifacts', 'agents', 'apps', 'home'].includes(view) ? view : null);

    // Preview column rides alongside chat, or alongside an agent's detail view.
    const hasPreview = preview.tabs.length > 0
        && !workspaceVisible
        && (view === 'chat' || (view === 'network' && !!agentState.selectedAgentId));

    const renderPreviewContent = (activeTab) => (
        <>
            {activeTab === 'browser' && preview.browserTabsList.length > 0 && (
                <BrowserPreview
                    tabs={browser.tabs}
                    selectedId={browser.selectedTabId}
                    onSelectTab={browser.setSelectedTabId}
                    onFullscreen={() => preview.setFullscreenItem({ kind: 'browser' })}
                    control={browser.control}
                    inputActive={preview.fullscreenItem?.kind !== 'browser'}
                />
            )}
            {activeTab?.startsWith('file:') && (() => {
                const fileKey = activeTab.slice(5);
                const file = preview.openFiles.find(f => (f.path || f.filename) === fileKey);
                return file ? (
                    <FilePreview
                        item={file}
                        onFullscreen={() => preview.setFullscreenItem({ kind: 'file', file })}
                    />
                ) : null;
            })()}
            {activeTab === 'terminal' && preview.terminalLines.length > 0 && (
                <TerminalPanel lines={preview.terminalLines} />
            )}
            {activeTab === 'desktop' && preview.desktopActive && (
                <DesktopPreview visible />
            )}
            {activeTab === 'generation' && preview.generationPreview && (
                <GenerationPreview preview={preview.generationPreview} />
            )}
        </>
    );

    // Show setup wizard if setup is not complete
    if (setupComplete === false) {
        return (
            <SetupWizard onComplete={() => {
                setSetupComplete(true);
                profilesHook.refresh();
            }} />
        );
    }

    // Still loading setup status
    if (setupComplete === null) {
        return null;
    }

    return (
        <div className={styles.appShell}>
            <div className={styles.bodyRow}>
                {/* Navigation sidebar */}
                <Sidebar
                    activePanel={activeSidebarPanel}
                    onNewConversation={newConversation}
                    audio={pendingAudio}
                    muted={muted}
                    onToggleMute={() => setMuted((m) => !m)}
                    onAudioEnded={() => setPendingAudio(null)}
                    desktopEnabled={features.desktop}
                    onOpenDesktop={openDesktop}
                    onLoadConversation={handleLoadConversation}
                    activeConversationId={activeConversationId}
                    onPanelToggle={handlePanelToggle}
                    customAppsEnabled={features.custom_apps}
                    homeAppEnabled={Boolean(homeAppSlug)}
                />

                {/* Main content area */}
                <div className={styles.mainContent}>
                    {/* Settings page — full view when settings icon clicked */}
                    {view === 'settings' && (
                        <SettingsPage
                            memoryRefreshSignal={memoryRefreshSignal}
                            toolsRefreshSignal={toolsRefreshSignal}
                        />
                    )}
                    {/* memoryRefreshSignal and toolsRefreshSignal are bumped
                     * by streaming events (remember/forget, tool_created)
                     * so the corresponding Settings tabs refetch on next
                     * open. */}

                    {/* Routines view — self-contained, owns its own routines state */}
                    {view === 'routines' && <RoutinesView onComposeInChat={composeInNewChat} />}
                    {/* Agents view — agent profiles, list → detail like Routines */}
                    {view === 'agents' && <AgentsView />}
                    {/* Global artifacts hub — full view from the sidebar */}
                    {view === 'artifacts' && (
                        <ArtifactsHubView onOpenConversation={openArtifactInConversation} />
                    )}
                    {view === 'apps' && features.custom_apps && (
                        <AppsView
                            homeAppSlug={homeAppSlug}
                            onHomeAppChange={handleHomeAppChange}
                            onOpenApp={openAppFull}
                            onOpenAppBesideChat={openAppBesideChat}
                        />
                    )}
                    {view === 'home' && features.custom_apps && homeAppSlug && (
                        <HomeView
                            slug={homeAppSlug}
                            onOpenApps={openAppsLibrary}
                            onHomeAppChange={handleHomeAppChange}
                            onOpenApp={openHomeWorkspace}
                        />
                    )}

                    {view === 'network' && !agentState.selectedAgentId && (
                        <div className={styles.networkArea}>
                            <AgentNetwork onClose={handleCloseNetwork} agentCount={networkAgentCount} />
                        </div>
                    )}

                    {/* Agent activity — left column when drilling into an agent */}
                    {view === 'network' && agentState.selectedAgentId && (
                        <div className={styles.chatColumn}
                             style={{ width: hasPreview ? `${preview.splitPosition}%` : '100%' }}>
                            <AgentActivityView
                                onNudge={sendNudge}
                                onPreview={openPreviewFromChat}
                                nudgeDisabled={stopRequested}
                            />
                        </div>
                    )}

                    {/* Chat — always mounted, hidden when another view is active */}
                    <div className={`${styles.chatColumn} ${view !== 'chat' && !workspaceSplit ? styles.hidden : ''}`}
                         style={{ width: (hasPreview && view === 'chat') || workspaceSplit ? `${preview.splitPosition}%` : '100%' }}>
                        <ChatPanel
                            turns={turns}
                            stalled={stalled}
                            onSend={handleSend}
                            onStop={stopGeneration}
                            isStreaming={isStreaming}
                            stopRequested={stopRequested}
                            attachment={attachment}
                            networkActivated={agentState.networkActivated}
                            networkAgentCount={networkAgentCount}
                            networkRunningCount={networkRunningCount}
                            onOpenNetwork={handleOpenNetwork}
                            onSelectAgent={handleSelectAgent}
                            selectedProfileId={selectedProfileId}
                            onProfileChange={handleProfileChange}
                            profileRefreshSignal={profilesHook.revision}
                            onPreview={openPreviewFromChat}
                            conversationId={activeConversationId}
                            draft={draft}
                            onDraftChange={setDraft}
                        />
                    </div>

                    {workspaceSplit && <SplitHandle onDrag={preview.setSplitPosition} />}

                    {workspaceApp && (
                        <CustomAppWorkspace
                            app={workspaceApp}
                            visible={workspaceVisible}
                            layout={workspaceLayout}
                            origin={workspaceOrigin}
                            homeAppSlug={homeAppSlug}
                            tabs={workspaceTabs}
                            activeTab={workspaceActiveTab}
                            onTabChange={handleWorkspaceTabChange}
                            onCloseTab={handleWorkspaceCloseTab}
                            onOpenChat={openChatBesideApp}
                            onComposeChat={composeFromApp}
                            onOpenApps={openAppsLibrary}
                            onHomeAppChange={handleHomeAppChange}
                        >
                            {renderPreviewContent(workspaceActiveTab)}
                        </CustomAppWorkspace>
                    )}

                    {/* Shared split handle + preview panel — visible alongside chat OR agent activity */}
                    {hasPreview && (
                        <>
                            <SplitHandle onDrag={preview.setSplitPosition} />
                            <div className={styles.previewColumn}>
                                <PreviewPanel
                                    tabs={preview.tabs}
                                    activeTab={preview.activeTab}
                                    onTabChange={preview.setActiveTab}
                                    onCloseTab={preview.closeTab}
                                >
                                    {renderPreviewContent(preview.activeTab)}
                                </PreviewPanel>
                            </div>
                        </>
                    )}
                </div>
            </div>

            {/* User's personal desktop overlay — opened via the header button,
                independent of any agent's desktop. Floats on top of all views. */}
            {userDesktopOpen && (
                <DesktopPreview visible={true} onClose={() => setUserDesktopOpen(false)} overlay />
            )}

            {/* Fullscreen preview — fills entire viewport */}
            {preview.fullscreenItem?.kind === 'file' && (
                <FilePreview
                    item={preview.fullscreenItem.file}
                    fullscreen
                    onClose={() => preview.setFullscreenItem(null)}
                />
            )}
            {preview.fullscreenItem?.kind === 'browser' && browser.tabs.length > 0 && (
                <BrowserFullscreen
                    snapshot={(browser.tabs.find((t) => t.id === browser.selectedTabId) || browser.tabs[0]).snapshot}
                    control={browser.control}
                    onClose={() => preview.setFullscreenItem(null)}
                />
            )}

        </div>
    );
}

/** Wraps the app in the agent state provider so all children can read/update agent data. */
export default function DesktopApp(props) {
    return (
        <AgentStateProvider>
            <ConversationsProvider>
                <DesktopAppInner {...props} />
            </ConversationsProvider>
        </AgentStateProvider>
    );
}
