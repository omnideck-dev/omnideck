import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import useArtifactNavigation from '../useArtifactNavigation.js';

const ARTIFACT = {
    id: 'artifact-1',
    conversation_id: 'conversation-2',
    filename: 'report.md',
    content_type: 'text/markdown',
    path: '/home/omnideck/report.md',
};

afterEach(() => vi.restoreAllMocks());

describe('useArtifactNavigation', () => {
    it('opens a conversation with only the artifact ID as navigation intent', async () => {
        const navigation = {
            openConversation: vi.fn().mockResolvedValue(true),
            openChat: vi.fn(),
        };
        const { result } = renderHook(() => useArtifactNavigation({
            destination: { kind: 'artifacts' },
            navigation,
            openWorkspacePreview: vi.fn(),
            onError: vi.fn(),
        }));

        await result.current(ARTIFACT);

        expect(navigation.openConversation).toHaveBeenCalledWith('conversation-2', {
            artifactId: 'artifact-1',
        });
    });

    it('resolves artifact intent into a workspace preview without a preview-state write', async () => {
        globalThis.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ARTIFACT,
        });
        const navigation = {
            openConversation: vi.fn(),
            openChat: vi.fn(),
        };
        const openWorkspacePreview = vi.fn();

        renderHook(() => useArtifactNavigation({
            destination: {
                kind: 'chat',
                conversationId: 'conversation-2',
                artifactId: 'artifact-1',
            },
            navigation,
            openWorkspacePreview,
            onError: vi.fn(),
        }));

        await waitFor(() => expect(openWorkspacePreview).toHaveBeenCalledWith({
            filename: 'report.md',
            content_type: 'text/markdown',
            path: '/home/omnideck/report.md',
        }));
        expect(globalThis.fetch).toHaveBeenCalledWith('/api/artifacts/artifact-1', {
            signal: expect.any(AbortSignal),
        });
        expect(navigation.openChat).toHaveBeenCalledWith('conversation-2');
        expect(globalThis.fetch).not.toHaveBeenCalledWith(
            expect.stringContaining('preview-state'),
            expect.anything(),
        );
    });
});
