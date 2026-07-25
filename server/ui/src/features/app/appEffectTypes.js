/**
 * One-time application effects can originate from any feature. Keep their
 * vocabulary independent from conversation events so future producers do not
 * need to depend on the conversation feature.
 */
export const APP_EFFECT_TYPES = Object.freeze(/** @type {const} */ ({
    PLAY_AUDIO: 'audio/play',
    REFRESH_CUSTOM_TOOLS: 'custom-tools/refresh',
    ROOT_WORKSPACE_RESOURCE_AVAILABLE: 'workspace/root-resource-available',
    CLOSE_CONVERSATION_WORKSPACE_VIEWS: 'workspace/close-conversation-views',
    OPEN_AGENT_WORKSPACE_RESOURCE: 'workspace/open-agent-resource',
    DESKTOP_VIEWS_CLOSING: 'desktop/views-closing',
    DESKTOP_VIEW_ACTION_REQUESTED: 'desktop/view-action-requested',
}));
