const DESTINATION_METADATA = {
    settings: { label: 'Settings', icon: 'bi-gear' },
    agents: { label: 'Agents', icon: 'bi-robot' },
    routines: { label: 'Routines', icon: 'bi-bullseye' },
    artifacts: { label: 'Artifacts', icon: 'bi-collection' },
    apps: { label: 'Custom Apps', icon: 'bi-grid' },
};

export function createDestinationSurface(destination) {
    if (destination.kind === 'chat' || destination.kind === 'network') {
        return {
            id: 'destination:conversation',
            kind: 'conversation',
            group: 'destination',
            label: 'Chat',
            icon: 'bi-chat-left-text',
            destination,
            closable: true,
        };
    }
    const metadata = DESTINATION_METADATA[destination.kind];
    if (!metadata || destination.kind === 'custom-app') return null;
    const scopedArtifactId = destination.kind === 'artifacts'
        && destination.conversationId
        ? `:${destination.conversationId}`
        : '';
    return {
        id: `destination:${destination.kind}${scopedArtifactId}`,
        kind: destination.kind,
        group: 'destination',
        label: scopedArtifactId ? 'Conversation artifacts' : metadata.label,
        icon: metadata.icon,
        destination,
        closable: true,
    };
}

export function createArtifactSurface(artifact) {
    if (!artifact?.id) return null;
    return {
        id: `artifact:${artifact.id}`,
        testid: `artifact:${artifact.filename}`,
        kind: 'artifact-file',
        group: 'artifact-file',
        resourceId: artifact.id,
        artifact,
        label: artifact.filename || 'Artifact',
        icon: 'bi-file-earmark',
        closable: true,
    };
}

export function createCustomAppSurface(app, reloadSignal = 0) {
    if (!app) return null;
    return {
        id: `custom-app:${app.slug}`,
        kind: 'custom-app',
        group: 'custom-app',
        resourceId: app.slug,
        label: app.title,
        icon: app.icon,
        app,
        reloadSignal,
        destination: { kind: 'custom-app', appSlug: app.slug },
        closable: true,
    };
}

export function createFileOutputSurface(item, conversationId) {
    const fileKey = item?.path || item?.filename;
    if (!fileKey) return null;
    return {
        id: `artifact-output:${conversationId || 'unknown'}:${encodeURIComponent(fileKey)}`,
        testid: `artifact:${item.filename || fileKey}`,
        kind: 'artifact-file',
        group: 'artifact-file',
        artifact: {
            ...item,
            conversation_id: conversationId || null,
        },
        label: item.filename || 'Artifact',
        icon: 'bi-file-earmark',
        closable: true,
    };
}

export function conversationExecutionSurfaceId(
    conversationId,
    agentId,
    resourceId,
    isRoot = false,
) {
    const producerId = isRoot ? 'root' : agentId;
    return `conversation-execution:${conversationId}:${producerId}:${resourceId}`;
}

export function createConversationExecutionSurface({
    conversationId,
    agentId,
    agentName,
    resourceId,
    isRoot = false,
}) {
    if (!conversationId || !agentId || !['browser', 'terminal'].includes(resourceId)) {
        return null;
    }
    const resourceLabel = resourceId === 'browser' ? 'Browser' : 'Terminal';
    const producerLabel = isRoot ? '' : (agentName || 'Agent');
    return {
        id: conversationExecutionSurfaceId(
            conversationId,
            agentId,
            resourceId,
            isRoot,
        ),
        testid: isRoot ? resourceId : `${agentId}:${resourceId}`,
        kind: 'conversation-execution',
        group: 'conversation-execution',
        conversationId,
        agentId,
        resourceId,
        isRoot,
        label: producerLabel
            ? `${producerLabel} · ${resourceLabel}`
            : resourceLabel,
        icon: resourceId === 'browser' ? 'bi-globe' : 'bi-terminal',
        closable: true,
    };
}
