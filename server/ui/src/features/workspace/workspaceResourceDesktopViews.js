export function workspaceResourceViewId(
    conversationId,
    agentId,
    resourceId,
    isRoot = false,
) {
    const producerId = isRoot ? 'root' : agentId;
    return `workspace-resource:${conversationId}:${producerId}:${resourceId}`;
}

function runtimeMetadata({ agentId, resourceId, isRoot }) {
    return {
        testid: isRoot ? resourceId : `${agentId}:${resourceId}`,
        testMetadata: {
            ownerId: agentId,
            resourceId,
        },
    };
}

/**
 * Workspace owns resource identity because it defines what counts as the same
 * Browser or Terminal across agent activity and application restores.
 */
export function createWorkspaceResourceView({
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
        id: workspaceResourceViewId(
            conversationId,
            agentId,
            resourceId,
            isRoot,
        ),
        ...runtimeMetadata({ agentId, resourceId, isRoot }),
        type: 'workspace-resource',
        identity: {
            conversationId,
            agentId,
            resourceId,
            isRoot,
        },
        label: producerLabel
            ? `${producerLabel} · ${resourceLabel}`
            : resourceLabel,
        icon: resourceId === 'browser' ? 'bi-globe' : 'bi-terminal',
        closable: true,
    };
}

export function workspaceResourceIdentityForView(view) {
    return view?.identity || {};
}

/** Restore Workspace-owned runtime metadata omitted from local storage. */
export function rehydrateWorkspaceResourceView(view) {
    const identity = workspaceResourceIdentityForView(view);
    if (!identity.agentId || !identity.resourceId) return null;
    return {
        ...view,
        ...runtimeMetadata(identity),
    };
}
