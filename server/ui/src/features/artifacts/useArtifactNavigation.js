import {
    useCallback,
    useEffect,
    useState,
} from 'react';

import {
    useAppEffectSubscription,
} from '../app/AppEffects.jsx';
import { APP_EFFECT_TYPES } from '../app/appEffectTypes.js';

/**
 * Own the Artifact domain's deferred ID resolution.
 *
 * Navigation first loads/focuses the source Conversation, then emits an
 * Artifact request. Keeping the pending ID here avoids storing an unresolved
 * domain key in either Desktop Layout or a parallel navigation store.
 */
export default function useArtifactNavigation({
    navigation,
    openArtifact,
    onError,
}) {
    const [pendingArtifact, setPendingArtifact] = useState(null);

    const handleOpenArtifactRequest = useCallback((effect) => {
        if (!effect.payload.artifactId) return;
        setPendingArtifact({
            artifactId: effect.payload.artifactId,
            conversationId: effect.payload.conversationId || null,
        });
    }, []);
    useAppEffectSubscription(
        APP_EFFECT_TYPES.OPEN_ARTIFACT_REQUESTED,
        handleOpenArtifactRequest,
    );

    useEffect(() => {
        if (!pendingArtifact?.artifactId) return undefined;
        const controller = new AbortController();
        const { artifactId } = pendingArtifact;
        fetch(
            `/api/artifacts/${encodeURIComponent(artifactId)}`,
            { signal: controller.signal },
        )
            .then(async (response) => {
                if (!response.ok) throw new Error('Artifact not found');
                return response.json();
            })
            .then((artifact) => {
                setPendingArtifact(null);
                openArtifact(artifact);
            })
            .catch((error) => {
                if (error.name === 'AbortError') return;
                setPendingArtifact(null);
                onError();
            });
        return () => controller.abort();
    }, [onError, openArtifact, pendingArtifact]);

    return useCallback((artifact) => (
        navigation.openConversation(artifact.conversation_id, {
            artifactId: artifact.id,
        })
    ), [navigation]);
}
