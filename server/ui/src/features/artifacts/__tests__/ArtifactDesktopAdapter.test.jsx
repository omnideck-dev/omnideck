import { render, waitFor } from '@testing-library/react';
import {
    afterEach,
    beforeEach,
    describe,
    expect,
    it,
    vi,
} from 'vitest';

import {
    ArtifactDesktopEffects,
} from '../ArtifactDesktopAdapter.jsx';

const desktop = vi.hoisted(() => ({
    catalog: { openViews: [] },
    commands: {
        openView: vi.fn(),
        preferredTabGroupId: vi.fn(() => 'right'),
        syncViews: vi.fn(),
    },
}));

vi.mock('../../desktop/DesktopViewRuntime.jsx', () => ({
    useDesktopViewCatalog: () => desktop.catalog,
    useDesktopViewCommands: () => desktop.commands,
}));

vi.mock('../../conversation/session/ConversationSession.jsx', () => ({
    useActiveConversationId: () => 'conversation-1',
}));

vi.mock('../../navigation/DesktopNavigation.jsx', () => ({
    useDesktopNavigationCommands: () => ({
        openConversation: vi.fn(),
    }),
}));

vi.mock('../../app/AppEffects.jsx', () => ({
    useAppEffectSubscription: vi.fn(),
}));

vi.mock('../../../components/ToastProvider.jsx', () => ({
    useToast: () => ({ addToast: vi.fn() }),
}));

vi.mock('../useArtifactNavigation.js', () => ({
    default: () => vi.fn(),
}));

const RESTORED_ARTIFACT = {
    id: 'artifact:artifact-7',
    type: 'artifact-file',
    identity: {
        resourceId: 'artifact-7',
        resourcePath: '/home/omnideck/report.md',
        conversationId: 'conversation-1',
    },
    label: 'report.md',
    icon: 'bi-file-earmark',
    closable: true,
};
const LIVE_ARTIFACT = {
    id: 'artifact-7',
    filename: 'report.md',
    path: '/home/omnideck/report.md',
    conversation_id: 'conversation-1',
    status: 'present',
};

describe('ArtifactDesktopEffects restore reconciliation', () => {
    beforeEach(() => {
        desktop.catalog.openViews = [RESTORED_ARTIFACT];
        Object.values(desktop.commands).forEach((command) => (
            command.mockClear()
        ));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it('rehydrates a durable Artifact key without changing its View ID', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => LIVE_ARTIFACT,
        });
        vi.stubGlobal('fetch', fetchMock);

        render(<ArtifactDesktopEffects />);

        await waitFor(() => expect(desktop.commands.syncViews)
            .toHaveBeenCalledWith({
                views: [expect.objectContaining({
                    id: RESTORED_ARTIFACT.id,
                    identity: expect.objectContaining({
                        resourceId: LIVE_ARTIFACT.id,
                    }),
                    artifact: LIVE_ARTIFACT,
                    actions: [expect.objectContaining({
                        id: 'open-source-conversation',
                    })],
                })],
                closeViewIds: [],
            }));
        expect(fetchMock).toHaveBeenCalledWith(
            '/api/artifacts/artifact-7',
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
    });

    it('closes a restored View whose Artifact no longer exists', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false,
            status: 404,
        }));

        render(<ArtifactDesktopEffects />);

        await waitFor(() => expect(desktop.commands.syncViews)
            .toHaveBeenCalledWith({
                views: [],
                closeViewIds: [RESTORED_ARTIFACT.id],
            }));
    });

    it('resolves legacy file-output Views by path within the conversation', async () => {
        const outputView = {
            ...RESTORED_ARTIFACT,
            id: 'artifact-output:conversation-1:%2Fhome%2Fomnideck%2Freport.md',
            identity: {
                ...RESTORED_ARTIFACT.identity,
                resourceId: null,
            },
        };
        desktop.catalog.openViews = [outputView];
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            status: 200,
            json: async () => ({ artifacts: [LIVE_ARTIFACT] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        render(<ArtifactDesktopEffects />);

        await waitFor(() => expect(desktop.commands.syncViews)
            .toHaveBeenCalledWith({
                views: [expect.objectContaining({
                    id: outputView.id,
                    identity: expect.objectContaining({
                        resourceId: LIVE_ARTIFACT.id,
                    }),
                    artifact: LIVE_ARTIFACT,
                })],
                closeViewIds: [],
            }));
        expect(fetchMock).toHaveBeenCalledWith(
            '/api/artifacts?conversation_id=conversation-1',
            expect.any(Object),
        );
    });
});
