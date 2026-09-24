import { describe, expect, it } from 'vitest';

import {
    ARTIFACTS_VIEW_ID,
    createNavigationView,
} from '../desktopNavigationViews.js';

describe('desktop navigation View descriptions', () => {
    it('uses one View identity for Chat, Network, and Agent Activity', () => {
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
            identity: {
                navigationTarget: {
                    kind: 'network',
                    agentId: 'agent-2',
                },
            },
        });
    });

    it('uses one Artifact library View identity and changes only its filter', () => {
        const scoped = createNavigationView({
            kind: 'artifacts',
            conversationId: 'conversation-2',
        });
        const unscoped = createNavigationView({ kind: 'artifacts' });

        expect(scoped).toMatchObject({
            id: ARTIFACTS_VIEW_ID,
            type: 'artifacts',
            label: 'Conversation artifacts',
            identity: {
                navigationTarget: {
                    kind: 'artifacts',
                    conversationId: 'conversation-2',
                },
            },
        });
        expect(unscoped).toMatchObject({
            id: ARTIFACTS_VIEW_ID,
            label: 'Artifacts',
            identity: {
                navigationTarget: { kind: 'artifacts' },
            },
        });
    });
});
