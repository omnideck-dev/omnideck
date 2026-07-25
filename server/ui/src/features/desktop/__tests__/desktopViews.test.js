import { describe, expect, it } from 'vitest';

import {
    ARTIFACTS_VIEW_ID,
    createArtifactView,
    createWorkspaceResourceView,
    createNavigationView,
    createFileOutputView,
    workspaceResourceViewId,
} from '../desktopViews.js';

describe('workspace resource view descriptions', () => {
    it('binds workspace identity explicitly to a conversation, agent, and resource', () => {
        const view = createWorkspaceResourceView({
            conversationId: 'conversation-1',
            agentId: 'agent-2',
            agentName: 'Researcher',
            resourceId: 'browser',
        });

        expect(view).toMatchObject({
            id: 'workspace-resource:conversation-1:agent-2:browser',
            type: 'workspace-resource',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
            resourceId: 'browser',
            label: 'Researcher · Browser',
        });
    });

    it('gives the same resource a distinct view identity for each agent', () => {
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

    it('keeps one logical root view across root-agent turns', () => {
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

describe('conversation view descriptions', () => {
    it('uses one view identity for Chat, Network, and Agent Activity', () => {
        const chat = createNavigationView({
            kind: 'chat',
            conversationId: 'conversation-1',
        });
        const activity = createNavigationView({
            kind: 'network',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
        });

        expect(chat.id).toBe('destination:conversation');
        expect(activity.id).toBe(chat.id);
        expect(activity).toMatchObject({
            type: 'conversation',
            navigationTarget: {
                kind: 'network',
                agentId: 'agent-2',
            },
        });
    });
});

describe('artifact view descriptions', () => {
    it('uses one library View identity and changes only its filter', () => {
        const scoped = createNavigationView({
            kind: 'artifacts',
            conversationId: 'conversation-2',
        });
        const unscoped = createNavigationView({ kind: 'artifacts' });

        expect(scoped).toMatchObject({
            id: ARTIFACTS_VIEW_ID,
            type: 'artifacts',
            label: 'Conversation artifacts',
            navigationTarget: {
                kind: 'artifacts',
                conversationId: 'conversation-2',
            },
        });
        expect(unscoped).toMatchObject({
            id: ARTIFACTS_VIEW_ID,
            label: 'Artifacts',
            navigationTarget: { kind: 'artifacts' },
        });
    });

    it('opens an artifact as a file view independent of workspace state', () => {
        const artifact = {
            id: 'artifact-7',
            filename: 'report.md',
        };

        expect(createArtifactView(artifact)).toMatchObject({
            id: 'artifact:artifact-7',
            testid: 'artifact:report.md',
            type: 'artifact-file',
            resourceId: 'artifact-7',
            artifact,
        });
    });

    it('opens a sent file as a durable artifact view', () => {
        const withoutId = createFileOutputView({
            filename: 'report.md',
            path: '/home/omnideck/report.md',
        }, 'conversation-2');
        const withId = createFileOutputView({
            id: 'artifact-2',
            filename: 'report.md',
            path: '/home/omnideck/report.md',
        }, 'conversation-2');

        expect(withoutId).toMatchObject({
            type: 'artifact-file',
            label: 'report.md',
            resourceId: null,
            resourcePath: '/home/omnideck/report.md',
            conversationId: 'conversation-2',
            actions: [],
            artifact: {
                conversation_id: 'conversation-2',
                path: '/home/omnideck/report.md',
            },
        });
        expect(withId.resourceId).toBe('artifact-2');
        expect(withId.actions).toEqual(['open-source-conversation']);
    });
});
