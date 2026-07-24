/**
 * One-time application effects can originate from any feature. Keep their
 * vocabulary independent from conversation events so future producers do not
 * need to depend on the conversation feature.
 */
export const APP_EFFECT_TYPES = Object.freeze(/** @type {const} */ ({
    PLAY_AUDIO: 'audio/play',
    REFRESH_CUSTOM_TOOLS: 'custom-tools/refresh',
    ROOT_EXECUTION_VIEW_AVAILABLE: 'conversation-execution/root-view-available',
    CLOSE_CONVERSATION_EXECUTION_VIEWS: 'conversation-execution/close-conversation',
}));
