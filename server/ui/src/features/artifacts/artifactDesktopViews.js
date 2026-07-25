/**
 * Artifact owns both the stable View ID and the durable lookup keys used to
 * rehydrate a file. Desktop treats all of these values as opaque identity.
 */
const OPEN_SOURCE_CONVERSATION_ACTION = Object.freeze({
    id: 'open-source-conversation',
    label: 'Open source conversation',
    icon: 'bi-chat-left-text',
    testid: 'artifact-open-conversation',
});

export function createArtifactView(artifact) {
    if (!artifact?.id) return null;
    return {
        id: `artifact:${artifact.id}`,
        testid: `artifact:${artifact.filename}`,
        type: 'artifact-file',
        identity: {
            resourceId: artifact.id,
            ...(artifact.path ? { resourcePath: artifact.path } : {}),
            ...(artifact.conversation_id
                ? { conversationId: artifact.conversation_id }
                : {}),
        },
        artifact,
        label: artifact.filename || 'Artifact',
        icon: 'bi-file-earmark',
        actions: artifact.conversation_id
            ? [OPEN_SOURCE_CONVERSATION_ACTION]
            : [],
        closable: true,
    };
}

export function createFileOutputView(item, conversationId) {
    const fileKey = item?.path || item?.filename;
    if (!fileKey) return null;
    return {
        id: `artifact-output:${conversationId || 'unknown'}:${encodeURIComponent(fileKey)}`,
        testid: `artifact:${item.filename || fileKey}`,
        type: 'artifact-file',
        identity: {
            // Older file-output events have only a path. The Artifact adapter
            // can resolve either key against its catalog after a restore.
            ...(item.id ? { resourceId: item.id } : {}),
            resourcePath: fileKey,
            ...(conversationId ? { conversationId } : {}),
        },
        artifact: {
            ...item,
            conversation_id: conversationId || null,
        },
        label: item.filename || 'Artifact',
        icon: 'bi-file-earmark',
        actions: conversationId && item.id
            ? [OPEN_SOURCE_CONVERSATION_ACTION]
            : [],
        closable: true,
    };
}
