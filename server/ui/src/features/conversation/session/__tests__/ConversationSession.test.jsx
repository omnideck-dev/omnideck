import { act, render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentProvider, useAgentState } from '../../../agent/AgentState.jsx';
import {
    AppEffectsProvider,
    useAppEffectSubscription,
} from '../../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../../app/appEffectTypes.js';
import {
    WorkspaceProvider,
    useWorkspaceState,
} from '../../../workspace/WorkspaceState.jsx';

const harness = vi.hoisted(() => ({
    dispatchers: null,
    addStartedConversation: vi.fn(),
    addToast: vi.fn(),
    effects: [],
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
        reattachActiveRun: vi.fn(),
        newConversation: vi.fn(),
        setDraft: vi.fn(),
    },
}));

vi.mock('../useConversationSessionController.js', () => ({
    default: (dispatchers) => {
        harness.dispatchers = dispatchers;
        return harness.controller;
    },
}));

vi.mock('../../catalog/ConversationCatalog.jsx', () => ({
    useConversationCatalog: () => ({
        addStartedConversation: harness.addStartedConversation,
    }),
}));

vi.mock('../../../../components/ToastProvider.jsx', () => ({
    useToast: () => ({ addToast: harness.addToast }),
}));

const {
    ConversationSessionProvider,
    useConversationSessionCommands,
    useConversationSessionState,
} = await import('../ConversationSession.jsx');

function renderSession() {
    let session;
    let agents;
    let workspaces;

    function Inspector() {
        // Tests may merge the two narrow values locally; production consumers
        // must choose the subscription width they actually need.
        session = {
            ...useConversationSessionState(),
            ...useConversationSessionCommands(),
        };
        agents = useAgentState();
        workspaces = useWorkspaceState();
        useAppEffectSubscription(
            APP_EFFECT_TYPES
                .CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED,
            (effect) => harness.effects.push(effect),
        );
        return null;
    }

    render(
        <AppEffectsProvider>
            <AgentProvider>
                <WorkspaceProvider>
                    <ConversationSessionProvider>
                        <Inspector />
                    </ConversationSessionProvider>
                </WorkspaceProvider>
            </AgentProvider>
        </AppEffectsProvider>,
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
    beforeEach(() => {
        vi.clearAllMocks();
        harness.effects = [];
        harness.controller.loadConversation.mockResolvedValue(null);
        harness.controller.reattachActiveRun.mockReset();
    });

    it('restores Workspace data without reopening historical Views', async () => {
        harness.controller.loadConversation.mockResolvedValue({
            conversationId: 'conversation-2',
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
        });
        const { getAgents, getSession, getWorkspaces } = renderSession();

        await act(async () => {
            expect(await getSession().loadConversation('conversation-2')).toBe(true);
        });

        expect(getAgents().agents['root-1'].activityLog).toEqual([]);
        expect(getWorkspaces().byAgentId['root-1'].openFiles).toEqual([]);
        expect(harness.effects).toContainEqual({
            type: APP_EFFECT_TYPES
                .CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED,
            payload: { conversationId: 'conversation-1' },
        });
        expect(getSession().conversationProfileId).toBe('profile-2');
    });

    it('resets both derived owners when starting a new conversation', () => {
        const { getAgents, getSession, getWorkspaces } = renderSession();
        act(() => harness.dispatchers.agentDispatch({
            type: 'AGENT_STARTED',
            agentId: 'root-1',
            agentName: 'Root',
            parentAgentId: null,
            instruction: null,
            correlationId: null,
            timestamp: Date.now(),
        }));
        act(() => harness.dispatchers.workspaceDispatch({
            type: 'WORKSPACE_AGENT_STARTED', agentId: 'root-1', parentAgentId: null,
        }));

        act(() => getSession().newConversation({ draft: 'next task' }));

        expect(harness.controller.newConversation).toHaveBeenCalledWith({ draft: 'next task' });
        expect(getAgents().agents).toEqual({});
        expect(getWorkspaces().byAgentId).toEqual({});
        expect(harness.effects).toContainEqual({
            type: APP_EFFECT_TYPES
                .CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED,
            payload: { conversationId: 'conversation-1' },
        });
    });

    it('restores agent state before reattaching to an active run', async () => {
        const loaded = {
            conversationId: 'conversation-2',
            events: [event('agent_started', {
                parent_agent_id: null,
                instruction: null,
                correlation_id: null,
            })],
            browserTabs: [],
            terminal: {},
            profileId: 'profile-2',
            activeRun: {
                run_id: 'run-1',
                status: 'running',
                last_seq: 1,
                resume_after_seq: 1,
            },
        };
        harness.controller.loadConversation.mockResolvedValue(loaded);
        harness.controller.reattachActiveRun.mockImplementation(() => {
            // A reattached stream may deliver its first event immediately. If
            // reattachment moves above RESET and restore, this update is lost.
            harness.dispatchers.agentDispatch({
                type: 'UPDATE_ITERATION',
                agentId: 'root-1',
                iteration: 2,
                maxIterations: 10,
                contextUsage: null,
            });
        });
        const { getAgents, getSession } = renderSession();

        await act(async () => {
            expect(await getSession().loadConversation('conversation-2')).toBe(true);
        });

        expect(getAgents().agents['root-1']).toMatchObject({
            status: 'running',
            iteration: 2,
            maxIterations: 10,
        });
        expect(harness.controller.reattachActiveRun).toHaveBeenCalledWith(loaded);
    });

    it('connects newly started conversations to the catalog owner', () => {
        const { getSession } = renderSession();

        act(() => {
            getSession().sendMessage('hello', null, 'profile-1');
            getSession().sendMessage('follow-up', null, 'profile-1');
        });

        expect(harness.addStartedConversation).toHaveBeenCalledOnce();
        expect(harness.addStartedConversation).toHaveBeenCalledWith({
            conversationId: 'conversation-1',
            firstMessage: 'hello',
        });
    });

    it('shows nudge results returned by the controller', async () => {
        harness.controller.sendNudge.mockResolvedValue({
            ok: false,
            status: 409,
            error: 'not running',
        });
        const { getSession } = renderSession();

        await act(async () => {
            await getSession().sendNudge('please stop');
        });

        expect(harness.addToast).toHaveBeenCalledWith(
            'Agent is no longer running',
            { type: 'warn', duration: 5000 },
        );
    });

    it('owns formatting when an external source composes into the draft', () => {
        const { getSession } = renderSession();

        act(() => getSession().composeFromSource({
            title: 'Text Lab',
            text: 'Review this',
            context: { selection: 'example' },
        }));

        const updateDraft = harness.controller.setDraft.mock.calls[0][0];
        expect(updateDraft('Existing')).toBe(
            'Existing\n\nReview this\n\n'
            + 'Context from Text Lab:\n{\n  "selection": "example"\n}',
        );
    });
});
