import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AgentProvider, useAgentState } from '../../../agent/AgentState.jsx';
import {
    WorkspaceProvider,
    useWorkspaceState,
} from '../../../workspace/WorkspaceState.jsx';

const harness = vi.hoisted(() => ({
    callbacks: null,
    addStartedConversation: vi.fn(),
    refreshCustomTools: vi.fn(),
    controller: {
        activeConversationId: 'conversation-1',
        turns: [],
        draft: '',
        isStreaming: false,
        stopRequested: false,
        stalled: false,
        sendMessage: vi.fn(),
        sendNudge: vi.fn(),
        stopGeneration: vi.fn(),
        loadConversation: vi.fn(),
        newConversation: vi.fn(),
        setDraft: vi.fn(),
        savePreviewState: vi.fn(),
    },
}));

vi.mock('../useConversationSessionController.js', () => ({
    default: (callbacks) => {
        harness.callbacks = callbacks;
        return harness.controller;
    },
}));

vi.mock('../../catalog/ConversationCatalog.jsx', () => ({
    useConversationCatalog: () => ({
        addStartedConversation: harness.addStartedConversation,
    }),
}));

vi.mock('../../../../components/ToastProvider.jsx', () => ({
    useToast: () => ({ addToast: vi.fn() }),
}));

vi.mock('../../../customTools/CustomToolsCatalog.jsx', () => ({
    useCustomToolsCatalog: () => ({ refreshCustomTools: harness.refreshCustomTools }),
}));

const {
    ConversationSessionProvider,
    useConversationSession,
} = await import('../ConversationSession.jsx');

function renderSession() {
    let session;
    let agents;
    let workspaces;

    function Inspector() {
        session = useConversationSession();
        agents = useAgentState();
        workspaces = useWorkspaceState();
        return null;
    }

    render(
        <AgentProvider>
            <WorkspaceProvider>
                <ConversationSessionProvider>
                    <Inspector />
                </ConversationSessionProvider>
            </WorkspaceProvider>
        </AgentProvider>,
    );

    return {
        getSession: () => session,
        getAgents: () => agents,
        getWorkspaces: () => workspaces,
    };
}

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        timestamp: '2026-07-20T12:00:00.000Z',
        conversation_id: 'conversation-1',
        agent_id: 'root-1',
        agent_name: 'Root',
        depth: 0,
        ...fields,
    };
}

describe('ConversationSessionProvider', () => {
    it('assembles a restored conversation into the agent and workspace owners', () => {
        const { getAgents, getSession, getWorkspaces } = renderSession();

        act(() => harness.callbacks.onConversationLoaded({
            events: [
                event('agent_started', {
                    parent_agent_id: null,
                    instruction: null,
                    correlation_id: null,
                }),
                event('iteration', {
                    iteration_index: 0,
                    thinking: null,
                    content: 'restored answer',
                    tool_calls: [],
                }),
                event('agent_completed', { status: 'success' }),
            ],
            browserTabs: [],
            terminal: {},
            previewState: {
                open_files: ['/tmp/report.md'],
                active_tab: 'file:/tmp/report.md',
            },
            profileId: 'profile-2',
        }));

        expect(getAgents().agents['root-1'].activityLog).toEqual([
            expect.objectContaining({ type: 'content', content: 'restored answer' }),
        ]);
        expect(getWorkspaces().byAgentId['root-1'].openFiles).toEqual([
            { type: 'file_output', filename: 'report.md', path: '/tmp/report.md' },
        ]);
        expect(getWorkspaces().restoredActiveTab).toBe('file:/tmp/report.md');
        expect(getSession().conversationProfileId).toBe('profile-2');
    });

    it('resets both derived owners when starting a new conversation', () => {
        const { getAgents, getSession, getWorkspaces } = renderSession();
        act(() => harness.callbacks.onAgentAction({
            type: 'AGENT_STARTED',
            agentId: 'root-1',
            agentName: 'Root',
            parentAgentId: null,
            instruction: null,
            correlationId: null,
            timestamp: Date.now(),
        }));
        act(() => harness.callbacks.onWorkspaceAction({
            type: 'WORKSPACE_AGENT_STARTED', agentId: 'root-1', parentAgentId: null,
        }));

        act(() => getSession().newConversation({ draft: 'next task' }));

        expect(harness.controller.newConversation).toHaveBeenCalledWith({ draft: 'next task' });
        expect(getAgents().agents).toEqual({});
        expect(getWorkspaces().byAgentId).toEqual({});
    });

    it('connects newly started conversations to the catalog owner', () => {
        renderSession();
        const started = { conversationId: 'conversation-2', firstMessage: 'hello' };
        act(() => harness.callbacks.onConversationStarted(started));
        expect(harness.addStartedConversation).toHaveBeenCalledWith(started);
    });

    it('refreshes the Custom Tools owner after a tool-created event', () => {
        renderSession();
        act(() => harness.callbacks.onToolCreated());
        expect(harness.refreshCustomTools).toHaveBeenCalledOnce();
    });
});
