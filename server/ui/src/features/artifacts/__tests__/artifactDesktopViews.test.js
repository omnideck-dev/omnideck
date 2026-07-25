import { describe, expect, it } from 'vitest';

import {
    createArtifactView,
    createFileOutputView,
} from '../artifactDesktopViews.js';

describe('Artifact desktop View descriptions', () => {
    it('opens an artifact as a file View independent of Workspace state', () => {
        const artifact = {
            id: 'artifact-7',
            filename: 'report.md',
        };

        expect(createArtifactView(artifact)).toMatchObject({
            id: 'artifact:artifact-7',
            testid: 'artifact:report.md',
            type: 'artifact-file',
            identity: {
                resourceId: 'artifact-7',
            },
            artifact,
        });
    });

    it('declares source navigation only when a file output has an ID', () => {
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
            identity: {
                resourcePath: '/home/omnideck/report.md',
                conversationId: 'conversation-2',
            },
            actions: [],
            artifact: {
                conversation_id: 'conversation-2',
                path: '/home/omnideck/report.md',
            },
        });
        expect(withId.identity.resourceId).toBe('artifact-2');
        expect(withId.actions).toEqual([{
            id: 'open-source-conversation',
            label: 'Open source conversation',
            icon: 'bi-chat-left-text',
            testid: 'artifact-open-conversation',
        }]);
    });
});
