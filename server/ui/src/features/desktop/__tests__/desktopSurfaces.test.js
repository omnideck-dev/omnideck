import { describe, expect, it } from 'vitest';

import {
    createArtifactSurface,
    createConversationExecutionSurface,
    createDestinationSurface,
    createFileOutputSurface,
    conversationExecutionSurfaceId,
} from '../desktopSurfaces.js';

describe('conversation execution surface descriptions', () => {
    it('binds execution identity explicitly to a conversation, agent, and resource', () => {
        const surface = createConversationExecutionSurface({
            conversationId: 'conversation-1',
            agentId: 'agent-2',
            agentName: 'Researcher',
            resourceId: 'browser',
        });

        expect(surface).toMatchObject({
            id: 'conversation-execution:conversation-1:agent-2:browser',
            kind: 'conversation-execution',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
            resourceId: 'browser',
            label: 'Researcher · Browser',
        });
    });

    it('gives the same resource a distinct surface identity for each agent', () => {
        expect(conversationExecutionSurfaceId(
            'conversation-1',
            'agent-1',
            'terminal',
        )).not.toBe(
            conversationExecutionSurfaceId(
                'conversation-1',
                'agent-2',
                'terminal',
            ),
        );
    });

    it('keeps one logical root surface across root-agent turns', () => {
        expect(conversationExecutionSurfaceId(
            'conversation-1',
            'root-turn-1',
            'browser',
            true,
        )).toBe(
            conversationExecutionSurfaceId(
                'conversation-1',
                'root-turn-2',
                'browser',
                true,
            ),
        );
    });
});

describe('conversation surface descriptions', () => {
    it('uses one surface identity for Chat, Network, and Agent Activity', () => {
        const chat = createDestinationSurface({
            kind: 'chat',
            conversationId: 'conversation-1',
        });
        const activity = createDestinationSurface({
            kind: 'network',
            conversationId: 'conversation-1',
            agentId: 'agent-2',
        });

        expect(chat.id).toBe('destination:conversation');
        expect(activity.id).toBe(chat.id);
        expect(activity).toMatchObject({
            kind: 'conversation',
            destination: {
                kind: 'network',
                agentId: 'agent-2',
            },
        });
    });
});

describe('artifact surface descriptions', () => {
    it('gives a conversation-scoped library its own stable identity', () => {
        const surface = createDestinationSurface({
            kind: 'artifacts',
            conversationId: 'conversation-2',
        });

        expect(surface).toMatchObject({
            id: 'destination:artifacts:conversation-2',
            kind: 'artifacts',
            label: 'Conversation artifacts',
            destination: {
                kind: 'artifacts',
                conversationId: 'conversation-2',
            },
        });
    });

    it('opens an artifact as a file surface independent of workspace state', () => {
        const artifact = {
            id: 'artifact-7',
            filename: 'report.md',
        };

        expect(createArtifactSurface(artifact)).toMatchObject({
            id: 'artifact:artifact-7',
            testid: 'artifact:report.md',
            kind: 'artifact-file',
            resourceId: 'artifact-7',
            artifact,
        });
    });

    it('opens a sent file as a durable artifact surface', () => {
        expect(createFileOutputSurface({
            filename: 'report.md',
            path: '/home/omnideck/report.md',
        }, 'conversation-2')).toMatchObject({
            kind: 'artifact-file',
            group: 'artifact-file',
            label: 'report.md',
            artifact: {
                conversation_id: 'conversation-2',
                path: '/home/omnideck/report.md',
            },
        });
    });
});
