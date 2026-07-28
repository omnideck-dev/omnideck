const DESTINATION_METADATA = {
    settings: { label: 'Settings', icon: 'bi-gear' },
    agents: { label: 'Agents', icon: 'bi-robot' },
    routines: { label: 'Routines', icon: 'bi-bullseye' },
    artifacts: { label: 'Artifacts', icon: 'bi-collection' },
    apps: { label: 'Apps', icon: 'bi-grid' },
};

export const CONVERSATION_VIEW_ID = 'destination:conversation';
export const ARTIFACTS_VIEW_ID = 'destination:artifacts';

/**
 * Navigation owns destination identity. Desktop sees only an opaque View ID
 * and an opaque serializable identity record.
 */
export function createNavigationView(navigationTarget) {
    if (navigationTarget.kind === 'chat' || navigationTarget.kind === 'network') {
        return {
            id: CONVERSATION_VIEW_ID,
            type: 'conversation',
            label: 'Chat',
            icon: 'bi-chat-left-text',
            identity: { navigationTarget },
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
        identity: { navigationTarget },
        closable: true,
    };
}

/** Read Navigation-owned identity without exposing its shape to Desktop. */
export function navigationTargetForView(view) {
    return view?.identity?.navigationTarget || null;
}
