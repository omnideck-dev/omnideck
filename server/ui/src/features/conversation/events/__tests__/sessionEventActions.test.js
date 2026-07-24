import { describe, expect, it } from 'vitest';
import { getSessionEventActions } from '../sessionEventActions.js';

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        agent_id: 'agent-1',
        depth: 0,
        ...fields,
    };
}

describe('getSessionEventActions', () => {
    it('retains transcript records and confirms user input', () => {
        const userMessage = event('user_message', { content: 'hello' });
        expect(getSessionEventActions(userMessage)).toEqual([
            { type: 'RETAIN_EVENT', event: userMessage },
            { type: 'CONFIRM_USER_MESSAGE' },
        ]);
    });

    it('tracks in-progress output and finalizes iterations', () => {
        const content = event('content', { content: 'partial' });
        const iteration = event('iteration', { content: 'complete' });

        expect(getSessionEventActions(content)).toEqual([
            { type: 'UPDATE_IN_PROGRESS_ITERATION', event: content },
        ]);
        expect(getSessionEventActions(iteration)).toEqual([
            { type: 'RETAIN_EVENT', event: iteration },
            { type: 'FINALIZE_ITERATION' },
        ]);
    });

    it('sets only root agents on the open session', () => {
        const root = event('agent_started', { parent_agent_id: null });
        const child = event('agent_started', { depth: 1, parent_agent_id: 'agent-1' });

        expect(getSessionEventActions(root)).toEqual([
            { type: 'RETAIN_EVENT', event: root },
            { type: 'SET_ROOT_AGENT', agentId: 'agent-1' },
        ]);
        expect(getSessionEventActions(child)).toEqual([]);
    });

    it('leaves sub-agent transcript activity to the agent owner', () => {
        const childFields = { agent_id: 'child-1', depth: 1, parent_agent_id: 'agent-1' };

        expect(getSessionEventActions(event('user_message', childFields))).toEqual([]);
        expect(getSessionEventActions(event('content', {
            ...childFields,
            content: 'partial child output',
        }))).toEqual([]);
        expect(getSessionEventActions(event('iteration', {
            ...childFields,
            content: 'complete child output',
        }))).toEqual([]);
        expect(getSessionEventActions(event('file_output', {
            ...childFields,
            filename: 'child.txt',
        }))).toEqual([]);
        expect(getSessionEventActions(event('error', {
            ...childFields,
            message: 'child failed',
        }))).toEqual([]);
    });

    it('finishes turns without retaining the boundary signal', () => {
        expect(getSessionEventActions(event('turn_end'))).toEqual([
            { type: 'FINISH_TURN' },
        ]);
    });

    it('ignores one-time, workspace-only, and missing events', () => {
        expect(getSessionEventActions(event('tool_created'))).toEqual([]);
        expect(getSessionEventActions(event('browser_screenshot'))).toEqual([]);
        expect(getSessionEventActions(null)).toEqual([]);
    });
});
