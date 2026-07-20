import { describe, expect, it } from 'vitest';
import { getWorkspaceEventActions } from '../workspaceEventHandler.js';

function event(type, fields = {}) {
    return {
        id: `event-${type}`,
        type,
        timestamp: '2026-07-20T12:00:00.000Z',
        conversation_id: 'conversation-1',
        agent_id: 'agent-1',
        depth: 0,
        ...fields,
    };
}

describe('getWorkspaceEventActions', () => {
    it('maps browser screenshots', () => {
        expect(getWorkspaceEventActions(event('browser_screenshot', {
            url: 'https://example.test',
            title: 'Example',
            screenshot: 'base64-image',
            tab_id: 'tab-1',
            open_tab_ids: ['tab-1', 'tab-2'],
        }))).toEqual([{
            type: 'UPDATE_BROWSER_SNAPSHOT',
            agentId: 'agent-1',
            snapshot: {
                url: 'https://example.test',
                title: 'Example',
                screenshot: 'base64-image',
                tabId: 'tab-1',
                openTabIds: ['tab-1', 'tab-2'],
                agentId: 'agent-1',
            },
        }]);
    });

    it('maps terminal, desktop, and generation events', () => {
        expect(getWorkspaceEventActions(event('terminal_output', {
            cmd_id: 'cmd-1', cmd: 'pwd', status: 'completed', stdout: '/tmp',
        }))[0]).toMatchObject({
            type: 'UPDATE_TERMINAL',
            agentId: 'agent-1',
            event: { type: 'terminal_output', cmd_id: 'cmd-1', agentId: 'agent-1' },
        });

        expect(getWorkspaceEventActions(event('desktop_active'))).toEqual([{
            type: 'UPDATE_DESKTOP_ACTIVE', agentId: 'agent-1',
        }]);

        expect(getWorkspaceEventActions(event('generation_preview', {
            gen_id: 'generation-1', status: 'generating', step: 2,
        }))[0]).toMatchObject({
            type: 'UPDATE_GENERATION_PREVIEW',
            agentId: 'agent-1',
            preview: { type: 'generation_preview', gen_id: 'generation-1', agentId: 'agent-1' },
        });
    });

    it('ignores unrelated and missing events', () => {
        expect(getWorkspaceEventActions(event('content'))).toEqual([]);
        expect(getWorkspaceEventActions(null)).toEqual([]);
    });
});
