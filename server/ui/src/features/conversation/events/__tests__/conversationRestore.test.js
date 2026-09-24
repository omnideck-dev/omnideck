import { describe, expect, it } from 'vitest';
import { getAgentEventActions } from '../agentEventActions.js';
import { getConversationRestorePlan } from '../conversationRestore.js';
import { normalizeLiveEvent } from '../normalizeEvent.js';
import { projectTurns } from '../projectTurns.js';

const TIMESTAMP = '2026-07-20T12:00:00.000Z';

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        timestamp: TIMESTAMP,
        conversation_id: 'conversation-1',
        agent_id: 'root-1',
        agent_name: 'Root',
        depth: 0,
        ...fields,
    };
}

function asLiveEnvelope(savedEvent) {
    const {
        id, timestamp, conversation_id: conversationId,
        agent_id: agentId, agent_name: agentName, depth, type, ...payload
    } = savedEvent;
    return {
        id,
        timestamp,
        conversation_id: conversationId,
        agent_id: agentId,
        agent_name: agentName,
        depth,
        payload: { type, ...payload },
    };
}

describe('getConversationRestorePlan', () => {
    it('uses the canonical agent event actions for a complete saved conversation', () => {
        const events = [
            event('agent_started', {
                parent_agent_id: null,
                instruction: 'Help',
                correlation_id: null,
            }),
            event('context_usage', {
                iteration: 1,
                max_iterations: 20,
                context_used: 500,
                context_limit: 4000,
                fill_ratio: 0.125,
                compaction_threshold: 0.8,
            }),
            event('iteration', {
                iteration_index: 0,
                thinking: 'reasoning',
                content: 'answer',
                tool_calls: [{ id: 'tool-1', name: 'shell', arguments: { cmd: 'pwd' } }],
            }),
            event('spawn_requested', { correlation_id: 'spawn-1' }),
            event('agent_started', {
                agent_id: 'child-1',
                agent_name: 'Researcher',
                depth: 1,
                parent_agent_id: 'root-1',
                instruction: 'Research',
                correlation_id: 'spawn-1',
            }),
            event('iteration', {
                agent_id: 'child-1',
                depth: 1,
                iteration_index: 0,
                thinking: null,
                content: 'child result',
                tool_calls: [],
            }),
            event('file_output', {
                filename: 'report.md',
                content_type: 'text/markdown',
                content: null,
                path: '/tmp/report.md',
                tool_call_id: 'tool-1',
            }),
            event('tool_created', { name: 'saved-tool' }),
            event('compaction', {
                summary_text: 'summary',
                user_intent_summary: 'intent',
                stats: null,
                kept_from_id: null,
            }),
            event('error', { message: 'visible failure', retryable: false }),
            event('agent_completed', {
                agent_id: 'child-1',
                depth: 1,
                status: 'success',
            }),
            event('agent_completed', { status: 'success' }),
        ];

        const liveEvents = events.map((savedEvent) => normalizeLiveEvent(asLiveEnvelope(savedEvent)));
        const liveActions = liveEvents.flatMap((liveEvent) => {
            const actions = getAgentEventActions(liveEvent);
            return [...actions.immediate, ...actions.batched];
        });

        expect(projectTurns(liveEvents)).toEqual(projectTurns(events));
        expect(getConversationRestorePlan({ events }).agentActions).toEqual(liveActions);
    });

    it('marks an unfinished saved agent stopped at its last event', () => {
        const events = [
            event('agent_started', {
                parent_agent_id: null,
                instruction: null,
                correlation_id: null,
            }),
            event('iteration', {
                timestamp: '2026-07-20T12:01:00.000Z',
                iteration_index: 0,
                thinking: null,
                content: 'partial answer',
                tool_calls: [],
            }),
        ];

        expect(getConversationRestorePlan({ events }).agentActions.at(-1)).toEqual({
            type: 'AGENT_COMPLETED',
            agentId: 'root-1',
            status: 'stopped',
            timestamp: Date.parse('2026-07-20T12:01:00.000Z'),
        });
    });

    it('leaves an unfinished agent running when an active run will reattach', () => {
        const events = [event('agent_started', {
            parent_agent_id: null,
            instruction: null,
            correlation_id: null,
        })];

        expect(getConversationRestorePlan({
            events,
            activeRun: {
                run_id: 'run-1',
                status: 'running',
                last_seq: 2,
                resume_after_seq: 1,
            },
        }).agentActions).not.toContainEqual(expect.objectContaining({
            type: 'AGENT_COMPLETED',
            status: 'stopped',
        }));
    });

    it('restores execution data without restoring presentation state', () => {
        const restore = getConversationRestorePlan({
            events: [event('agent_started', {
                parent_agent_id: null,
                instruction: null,
                correlation_id: null,
            })],
            browserTabs: [{
                agent_id: 'root-1',
                url: 'https://example.com',
                title: 'Example',
                screenshot: 'image-data',
                tab_id: '3',
            }],
            terminal: {
                'root-1': [{ cmd_id: 'command-1', cmd: 'pwd', stdout: '/tmp\n' }],
            },
            previewState: {
                open_files: ['/tmp/report.md'],
                active_tab: 'file:/tmp/report.md',
            },
        });

        expect(restore.workspaceActions).toEqual([
            {
                type: 'WORKSPACE_AGENT_STARTED',
                agentId: 'root-1',
                parentAgentId: null,
            },
            {
                type: 'UPDATE_BROWSER_SNAPSHOT',
                agentId: 'root-1',
                snapshot: {
                    url: 'https://example.com',
                    title: 'Example',
                    screenshot: 'image-data',
                    tabId: 3,
                    openTabIds: null,
                    agentId: 'root-1',
                },
            },
            {
                type: 'UPDATE_TERMINAL',
                agentId: 'root-1',
                event: {
                    cmd_id: 'command-1',
                    cmd: 'pwd',
                    stdout: '/tmp\n',
                    agentId: 'root-1',
                },
            },
        ]);
        expect(restore).not.toHaveProperty('activeTab');
    });

    it('returns an empty plan for missing restore data', () => {
        expect(getConversationRestorePlan(null)).toEqual({
            agentActions: [],
            workspaceActions: [],
        });
    });
});
