const DESTINATION_METADATA = {
    settings: { label: 'Settings', icon: 'bi-gear' },
    agents: { label: 'Agents', icon: 'bi-robot' },
    routines: { label: 'Routines', icon: 'bi-bullseye' },
    artifacts: { label: 'Artifacts', icon: 'bi-collection' },
    apps: { label: 'Custom Apps', icon: 'bi-grid' },
};

function isRecord(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export const CONVERSATION_VIEW_ID = 'destination:conversation';
export const ARTIFACTS_VIEW_ID = 'destination:artifacts';

export function customAppViewId(slug) {
    return `custom-app:${slug}`;
}

export function createNavigationView(navigationTarget) {
    if (navigationTarget.kind === 'chat' || navigationTarget.kind === 'network') {
        return {
            id: CONVERSATION_VIEW_ID,
            type: 'conversation',
            label: 'Chat',
            icon: 'bi-chat-left-text',
            navigationTarget,
            closable: true,
        };
    }
    const metadata = DESTINATION_METADATA[navigationTarget.kind];
    if (!metadata || navigationTarget.kind === 'custom-app') return null;
    const isConversationArtifacts = navigationTarget.kind === 'artifacts'
        && navigationTarget.conversationId;
    return {
        // Artifacts is one library View. conversationId changes its current
        // filter; it does not create a second logical View or tab.
        id: navigationTarget.kind === 'artifacts'
            ? ARTIFACTS_VIEW_ID
            : `destination:${navigationTarget.kind}`,
        type: navigationTarget.kind,
        label: isConversationArtifacts
            ? 'Conversation artifacts'
            : metadata.label,
        icon: metadata.icon,
        navigationTarget,
        closable: true,
    };
}

export function createArtifactView(artifact) {
    if (!artifact?.id) return null;
    return {
        id: `artifact:${artifact.id}`,
        testid: `artifact:${artifact.filename}`,
        type: 'artifact-file',
        resourceId: artifact.id,
        artifact,
        label: artifact.filename || 'Artifact',
        icon: 'bi-file-earmark',
        actions: artifact.conversation_id
            ? ['open-source-conversation']
            : [],
        closable: true,
    };
}

export function createCustomAppView(app, reloadSignal = 0) {
    if (!app) return null;
    return {
        id: customAppViewId(app.slug),
        type: 'custom-app',
        resourceId: app.slug,
        label: app.title,
        icon: app.icon,
        app,
        reloadSignal,
        navigationTarget: { kind: 'custom-app', appSlug: app.slug },
        actions: ['reload'],
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
        artifact: {
            ...item,
            conversation_id: conversationId || null,
        },
        label: item.filename || 'Artifact',
        icon: 'bi-file-earmark',
        actions: conversationId ? ['open-source-conversation'] : [],
        closable: true,
    };
}

export function workspaceResourceViewId(
    conversationId,
    agentId,
    resourceId,
    isRoot = false,
) {
    const producerId = isRoot ? 'root' : agentId;
    return `workspace-resource:${conversationId}:${producerId}:${resourceId}`;
}

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
        testid: isRoot ? resourceId : `${agentId}:${resourceId}`,
        type: 'workspace-resource',
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

/**
 * Restore validators live beside the View factories whose payloads they
 * describe. Persistence asks this registry a generic question instead of
 * encoding every feature's payload schema itself.
 */
export const DESKTOP_VIEW_VALIDATORS = Object.freeze({
    conversation: (view) => (
        isRecord(view.navigationTarget)
        && ['chat', 'network'].includes(view.navigationTarget.kind)
    ),
    'workspace-resource': (view) => (
        typeof view.conversationId === 'string'
        && typeof view.agentId === 'string'
        && ['browser', 'terminal'].includes(view.resourceId)
    ),
    'artifact-file': (view) => isRecord(view.artifact),
    'custom-app': (view) => (
        isRecord(view.app) && typeof view.app.slug === 'string'
    ),
    settings: () => true,
    agents: () => true,
    routines: () => true,
    artifacts: () => true,
    apps: () => true,
});

export function validDesktopView(view) {
    if (
        !isRecord(view)
        || typeof view.id !== 'string'
        || typeof view.type !== 'string'
        || typeof view.label !== 'string'
    ) {
        return false;
    }
    return Boolean(DESKTOP_VIEW_VALIDATORS[view.type]?.(view));
}
