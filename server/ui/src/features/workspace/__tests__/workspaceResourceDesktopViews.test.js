import { describe, expect, it } from 'vitest';

import {
    createWorkspaceResourceView,
    workspaceResourceViewId,
} from '../workspaceResourceDesktopViews.js';

describe('Workspace resource desktop View descriptions', () => {
    it('binds identity explicitly to a conversation, agent, and resource', () => {
        const view = createWorkspaceResourceView({
            conversationId: 'conversation-1',
            agentId: 'agent-2',
            agentName: 'Researcher',
            resourceId: 'browser',
        });

        expect(view).toMatchObject({
            id: 'workspace-resource:conversation-1:agent-2:browser',
            type: 'workspace-resource',
            identity: {
                conversationId: 'conversation-1',
                agentId: 'agent-2',
                resourceId: 'browser',
            },
            label: 'Researcher · Browser',
        });
    });

    it('gives the same resource a distinct View identity for each agent', () => {
        expect(workspaceResourceViewId(
            'conversation-1',
            'agent-1',
            'terminal',
        )).not.toBe(
            workspaceResourceViewId(
                'conversation-1',
                'agent-2',
                'terminal',
            ),
        );
    });

    it('keeps one logical root View across root-agent turns', () => {
        expect(workspaceResourceViewId(
            'conversation-1',
            'root-turn-1',
            'browser',
            true,
        )).toBe(
            workspaceResourceViewId(
                'conversation-1',
                'root-turn-2',
                'browser',
                true,
            ),
        );
    });
});
