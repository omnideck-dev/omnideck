import { useCallback, useEffect, useMemo } from 'react';

import BrowserIcon from '../../components/icons/BrowserIcon.jsx';
import DesktopIcon from '../../components/icons/DesktopIcon.jsx';
import FileIcon from '../../components/icons/FileIcon.jsx';
import SparkleIcon from '../../components/icons/SparkleIcon.jsx';
import TerminalIcon from '../../components/icons/TerminalIcon.jsx';
import { useAgentState } from '../agent/AgentState.jsx';
import useBrowserTabs from './useBrowserTabs.js';
import { useWorkspaceDispatch, useWorkspaceState } from './WorkspaceState.jsx';

/**
 * Builds the preview model for the visible agent and coordinates the browser
 * control session and saved preview metadata. Desktop layout only needs the
 * returned preview and browser models; it does not need to know their rules.
 */
export default function useWorkspacePreview({
    conversationId,
    isStreaming,
    selectedAgentId = null,
    savePreviewState,
}) {
    const agentState = useAgentState();
    const workspaceState = useWorkspaceState();
    const workspaceDispatch = useWorkspaceDispatch();
    const { activeTab, splitPosition, fullscreenItem } = workspaceState.presentation;

    const setActiveTab = useCallback((nextActiveTab) => {
        workspaceDispatch({ type: 'SELECT_PREVIEW_TAB', activeTab: nextActiveTab });
    }, [workspaceDispatch]);
    const setSplitPosition = useCallback((position) => {
        workspaceDispatch({ type: 'SET_PREVIEW_SPLIT_POSITION', position });
    }, [workspaceDispatch]);
    const setFullscreenItem = useCallback((item) => {
        workspaceDispatch({ type: 'SET_FULLSCREEN_ITEM', item });
    }, [workspaceDispatch]);

    const rootAgent = agentState.rootId ? agentState.agents[agentState.rootId] : null;
    const previewAgent = (
        selectedAgentId && agentState.agents[selectedAgentId]
    ) || rootAgent;
    const previewWorkspace = previewAgent ? workspaceState.byAgentId[previewAgent.id] : null;

    const browserTabs = previewWorkspace?.browserTabs || {};
    const browserTabsList = useMemo(() => {
        const entries = Object.entries(browserTabs).map(([key, snapshot]) => ({
            id: Number(key),
            snapshot,
        }));
        entries.sort((a, b) => a.id - b.id);
        return entries;
    }, [browserTabs]);

    const terminalLines = previewWorkspace?.terminalLines || [];
    const desktopActive = previewWorkspace?.desktopActive || false;
    const generationPreview = previewWorkspace?.generationPreview || null;
    const openFiles = previewWorkspace?.openFiles || [];

    const tabs = useMemo(() => {
        const result = [];
        if (browserTabsList.length > 0) {
            result.push({
                id: 'browser',
                testid: 'browser',
                label: 'Browser',
                icon: <BrowserIcon size={14} />,
            });
        }
        for (const file of openFiles) {
            const key = file.path || file.filename;
            result.push({
                id: `file:${key}`,
                testid: `file:${file.filename}`,
                label: file.filename || 'File',
                icon: <FileIcon size={14} />,
            });
        }
        if (terminalLines.length > 0) {
            result.push({
                id: 'terminal',
                testid: 'terminal',
                label: 'Terminal',
                icon: <TerminalIcon size={14} />,
            });
        }
        if (desktopActive) {
            result.push({
                id: 'desktop',
                testid: 'desktop',
                label: 'Desktop',
                icon: <DesktopIcon size={14} />,
            });
        }
        if (generationPreview) {
            result.push({
                id: 'generation',
                testid: 'generation',
                label: 'Generation',
                icon: <SparkleIcon size={14} />,
            });
        }
        return result;
    }, [browserTabsList.length, desktopActive, generationPreview, openFiles, terminalLines.length]);

    useEffect(() => {
        if (tabs.length === 0) {
            if (activeTab !== null) setActiveTab(null);
        } else if (!tabs.some((tab) => tab.id === activeTab)) {
            setActiveTab(tabs[tabs.length - 1].id);
        }
    }, [activeTab, setActiveTab, tabs]);

    useEffect(() => {
        const target = workspaceState.restoredActiveTab;
        if (target === null || !tabs.some((tab) => tab.id === target)) return;
        setActiveTab(target);
        workspaceDispatch({ type: 'CONSUME_RESTORED_ACTIVE_TAB' });
    }, [setActiveTab, tabs, workspaceDispatch, workspaceState.restoredActiveTab]);

    const activeFile = activeTab?.startsWith('file:')
        ? openFiles.find((file) => (file.path || file.filename) === activeTab.slice(5))
        : null;

    const openFile = useCallback((item) => {
        const agentId = previewAgent?.id;
        if (!agentId) return;
        workspaceDispatch({ type: 'OPEN_FILE', agentId, item });
        setActiveTab(`file:${item.path || item.filename}`);
    }, [previewAgent?.id, setActiveTab, workspaceDispatch]);

    const closeTab = useCallback((id) => {
        const agentId = previewAgent?.id;
        if (!agentId) return;

        const actions = {
            browser: { type: 'CLEAR_BROWSER_TABS', agentId },
            terminal: { type: 'CLEAR_TERMINAL', agentId },
            desktop: { type: 'CLEAR_DESKTOP', agentId },
            generation: { type: 'CLEAR_GENERATION_PREVIEW', agentId },
        };
        const action = id.startsWith('file:')
            ? { type: 'CLOSE_FILE', agentId, fileKey: id.slice(5) }
            : actions[id];
        if (action) workspaceDispatch(action);

        const remaining = tabs.filter((tab) => tab.id !== id);
        setActiveTab(remaining.at(-1)?.id || null);
    }, [previewAgent?.id, setActiveTab, tabs, workspaceDispatch]);

    const browser = useBrowserTabs({
        conversationId,
        canControl: !isStreaming,
        enabled: browserTabsList.length > 0
            && (activeTab === 'browser' || fullscreenItem?.kind === 'browser'),
        agentTabs: browserTabsList,
    });

    const savedPreview = useMemo(() => {
        const hasTab = (id) => tabs.some((tab) => tab.id === id);
        return {
            open_files: openFiles.map((file) => file.path || file.filename).filter(Boolean),
            active_tab: activeTab,
            browser_visible: hasTab('browser'),
            terminal_visible: hasTab('terminal'),
            desktop_visible: hasTab('desktop'),
            generation_visible: hasTab('generation'),
        };
    }, [activeTab, openFiles, tabs]);

    useEffect(() => {
        // A selected sub-agent's preview is temporary. Conversation restore
        // starts at the root, so saving it would attach files to the wrong
        // visible workspace on reopen.
        if (selectedAgentId && selectedAgentId !== agentState.rootId) return undefined;
        const empty = !savedPreview.open_files.length
            && !savedPreview.active_tab
            && !savedPreview.browser_visible
            && !savedPreview.terminal_visible
            && !savedPreview.desktop_visible
            && !savedPreview.generation_visible;
        if (empty) return undefined;
        const handle = setTimeout(() => savePreviewState(savedPreview), 500);
        return () => clearTimeout(handle);
    }, [agentState.rootId, savePreviewState, savedPreview, selectedAgentId]);

    return {
        preview: {
            tabs,
            activeTab,
            setActiveTab,
            splitPosition,
            setSplitPosition,
            fullscreenItem,
            setFullscreenItem,
            activeFile,
            openFile,
            closeTab,
            browserTabsList,
            terminalLines,
            desktopActive,
            generationPreview,
            openFiles,
            previewAgent,
        },
        browser,
    };
}
