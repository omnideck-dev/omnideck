/**
 * One-time application effects can originate from any feature. Keep their
 * vocabulary independent from conversation events so future producers do not
 * need to depend on the conversation feature.
 */
export const APP_EFFECT_TYPES = Object.freeze(/** @type {const} */ ({
    PLAY_AUDIO_REQUESTED: 'audio/play-requested',
    REFRESH_CUSTOM_TOOLS_REQUESTED: 'custom-tools/refresh-requested',
    ROOT_WORKSPACE_RESOURCE_AVAILABLE: 'workspace/root-resource-available',
    CLOSE_CONVERSATION_WORKSPACE_VIEWS_REQUESTED:
        'workspace/close-conversation-views-requested',
    OPEN_AGENT_WORKSPACE_RESOURCE_REQUESTED:
        'workspace/open-agent-resource-requested',
    OPEN_CUSTOM_APP_REQUESTED: 'custom-apps/open-requested',
    OPEN_ARTIFACT_REQUESTED: 'artifacts/open-requested',
    DESKTOP_VIEWS_CLOSING: 'desktop/views-closing',
    DESKTOP_VIEW_ACTION_REQUESTED: 'desktop/view-action-requested',
}));
