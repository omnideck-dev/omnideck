import { useCallback, useEffect } from 'react';

/** Resolves a serializable artifact ID after its source conversation loads. */
export default function useArtifactNavigation({
    navigationTarget,
    navigation,
    openArtifact,
    onError,
}) {
    const openArtifactInConversation = useCallback((artifact) => (
        navigation.openConversation(artifact.conversation_id, { artifactId: artifact.id })
    ), [navigation]);

    useEffect(() => {
        const artifactId = navigationTarget.kind === 'chat' ? navigationTarget.artifactId : null;
        if (!artifactId) return undefined;
        const controller = new AbortController();
        fetch(`/api/artifacts/${encodeURIComponent(artifactId)}`, { signal: controller.signal })
            .then(async (response) => {
                if (!response.ok) throw new Error('Artifact not found');
                return response.json();
            })
            .then((artifact) => {
                navigation.openChat(navigationTarget.conversationId);
                openArtifact(artifact);
            })
            .catch((error) => {
                if (error.name === 'AbortError') return;
                onError();
                navigation.openChat(navigationTarget.conversationId);
            });
        return () => controller.abort();
    }, [navigationTarget, navigation, onError, openArtifact]);

    return openArtifactInConversation;
}
