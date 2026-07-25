import {
    act,
    renderHook,
    waitFor,
} from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import {
    AppEffectsProvider,
    useAppEffectDispatch,
} from '../../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../../app/appEffectTypes.js';
import useArtifactNavigation from '../useArtifactNavigation.js';

const ARTIFACT = {
    id: 'artifact-1',
    conversation_id: 'conversation-2',
    filename: 'report.md',
    content_type: 'text/markdown',
    path: '/home/omnideck/report.md',
};

const wrapper = ({ children }) => (
    <AppEffectsProvider>
        {children}
    </AppEffectsProvider>
);

afterEach(() => vi.restoreAllMocks());

describe('useArtifactNavigation', () => {
    it('opens a conversation with only the artifact ID as deferred intent', async () => {
        const navigation = {
            openConversation: vi.fn().mockResolvedValue(true),
        };
        const { result } = renderHook(() => useArtifactNavigation({
            navigation,
            openArtifact: vi.fn(),
            onError: vi.fn(),
        }), { wrapper });

        await result.current(ARTIFACT);

        expect(navigation.openConversation).toHaveBeenCalledWith(
            'conversation-2',
            { artifactId: 'artifact-1' },
        );
    });

    it('resolves an Artifact-domain request into a durable View', async () => {
        globalThis.fetch = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ARTIFACT,
        });
        const navigation = {
            openConversation: vi.fn(),
        };
        const openArtifact = vi.fn();

        const { result } = renderHook(() => ({
            dispatch: useAppEffectDispatch(),
            openArtifactInConversation: useArtifactNavigation({
                navigation,
                openArtifact,
                onError: vi.fn(),
            }),
        }), { wrapper });

        act(() => result.current.dispatch({
            type: APP_EFFECT_TYPES.OPEN_ARTIFACT_REQUESTED,
            artifactId: 'artifact-1',
            conversationId: 'conversation-2',
        }));

        await waitFor(() => expect(openArtifact).toHaveBeenCalledWith(
            ARTIFACT,
        ));
        expect(globalThis.fetch).toHaveBeenCalledWith(
            '/api/artifacts/artifact-1',
            { signal: expect.any(AbortSignal) },
        );
        expect(navigation.openConversation).not.toHaveBeenCalled();
    });
});
