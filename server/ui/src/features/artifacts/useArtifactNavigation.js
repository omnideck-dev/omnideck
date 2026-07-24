import { useCallback, useEffect } from 'react';

/** Resolves a serializable artifact ID after its source conversation loads. */
export default function useArtifactNavigation({
    destination,
    navigation,
    openArtifact,
    onError,
}) {
    const openArtifactInConversation = useCallback((artifact) => (
        navigation.openConversation(artifact.conversation_id, { artifactId: artifact.id })
    ), [navigation]);

    useEffect(() => {
        const artifactId = destination.kind === 'chat' ? destination.artifactId : null;
        if (!artifactId) return undefined;
        const controller = new AbortController();
        fetch(`/api/artifacts/${encodeURIComponent(artifactId)}`, { signal: controller.signal })
            .then(async (response) => {
                if (!response.ok) throw new Error('Artifact not found');
                return response.json();
            })
            .then((artifact) => {
                navigation.openChat(destination.conversationId);
                openArtifact(artifact);
            })
            .catch((error) => {
                if (error.name === 'AbortError') return;
                onError();
                navigation.openChat(destination.conversationId);
            });
        return () => controller.abort();
    }, [destination, navigation, onError, openArtifact]);

    return openArtifactInConversation;
}
